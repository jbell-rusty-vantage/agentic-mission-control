"""The Deep Agents lane's model routes (OC-R6 / OVE-200).

The lane builds its chat model from the resolved Model Catalog pin only: the compile seals the
pin's vendor and model id beside the deployment's served definition ref, and the materializer's
factory dispatches on the sealed vendor. The vendor feature rows live in the lane package.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from mission_control.adapters.capabilities.capability_pins import CapabilityPins
from mission_control.adapters.deep_agents.compile import (
    DeepAgentsCompileAdapter,
    DeepAgentsDeploymentFacts,
    ModelPinMismatch,
    catalog_model_components,
    deep_agents_lane,
)
from mission_control.adapters.deep_agents.materializer import (
    ExactModelFactory,
    IdentityCheckedModelFactory,
)
from mission_control.adapters.deep_agents.routes import (
    AGENT_FEATURES,
    DEEP_AGENTS_MODEL_ROUTES,
    VENDOR_FEATURES,
)
from mission_control.adapters.temporal.deployment_composition import (
    DeploymentCapabilityComponents,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchBindings,
    ServedModel,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestScope,
)
from mission_control.application.resolution.lane_options import LaneOptionsChecks
from mission_control.bootstrap.manifests import served_components
from mission_control.bootstrap.settings import get_settings
from mission_control.domain.capabilities.features import LANE_FEATURES, resolve_agent_configuration
from mission_control.domain.execution.errors import DeepAgentMaterializationError
from mission_control.domain.execution.materialization_receipt import MaterializationItem
from mission_control.domain.resolution.configuration import AgentConfiguration
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.conformance.lanes.compile.deep_agents import (
    AuthoredDeepAgentsAdapter,
    deep_agents_facts,
)
from tests.conformance.lanes.compile.fixtures import canonical_agent
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.models import checked_in_catalog, fixture_model_catalog
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings, fixture_served
from tests.unit.authoring.test_manifest_launch_inputs import MINIMAL, SCOPE

PINS = Path(__file__).resolve().parents[3] / "infra/capability-pins/research-capabilities.json"
SECRETS = {
    "environment:OPENAI_API_KEY": "test-openai-key",
    "environment:ANTHROPIC_API_KEY": "test-anthropic-key",
}


def _with_model(agent: AgentConfiguration, **update: object) -> AgentConfiguration:
    return AgentConfiguration.create(
        lane_profile=agent.lane_profile,
        node_ref=agent.node_ref,
        instructions_ref=agent.instructions_ref,
        model=agent.model.model_copy(update=update),
        items=agent.items,
        budgets=agent.budgets,
        data_class=agent.data_class,
        data_class_source=agent.data_class_source,
    )


@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_compile_seals_the_vendor_and_model_id_of_the_resolved_pin(vendor: str) -> None:
    facts = deep_agents_facts()
    agent = canonical_agent("deep_agents", vendor=vendor)  # type: ignore[arg-type]
    # A model id the deployment bindings never name: only the pin can supply it.
    pinned = _with_model(agent, model_id=f"{agent.model.model_id}-pinned")
    component, _effort, _verbosity = DeepAgentsCompileAdapter._model(pinned, facts)
    assert (component.provider, component.model_name) == (vendor, pinned.model.model_id)
    # The served definition ref and default settings are the deployment binding's.
    bound = facts.model_profiles[agent.model.profile]
    assert component.ref == bound.ref


def test_the_deployment_model_bindings_are_references_into_the_catalog() -> None:
    bindings = fixture_bindings()
    catalog = fixture_model_catalog(vendor="anthropic", model_id="claude-haiku-5-5")
    components = catalog_model_components(bindings.model_profiles, catalog)
    assert {
        name: (item.provider, item.model_name) for name, item in components.items()
    } == dict.fromkeys(bindings.model_profiles, ("anthropic", "claude-haiku-5-5"))
    with pytest.raises(ValueError, match="does not declare"):
        DeepAgentsDeploymentFacts.from_bindings(
            bindings, fixture_served(bindings), models=checked_in_catalog()
        )


def test_a_legacy_model_binding_naming_its_own_vendor_is_refused() -> None:
    document = fixture_bindings().model_dump(mode="json")
    document["model_profiles"]["frontier.default"].update(
        {"provider": "openai", "model_name": "gpt-5.4-nano"}
    )
    with pytest.raises(ValueError, match="provider|model_name"):
        ManifestLaunchBindings.model_validate(document)


@pytest.mark.parametrize(
    ("vendor", "model_id", "client"),
    [("anthropic", "claude-haiku-5-5", ChatAnthropic), ("openai", "gpt-5.6-luna", ChatOpenAI)],
)
def test_the_exact_model_factory_builds_the_sealed_vendor(
    vendor: str, model_id: str, client: type
) -> None:
    binding, _profile, _bundle = exact_fixture()
    sealed = binding.model_copy(
        update={
            "model": binding.model.model_copy(
                update={"provider": vendor, "model_name": model_id, "settings": {}}
            )
        }
    )
    model = ExactModelFactory()(sealed, SECRETS)
    assert isinstance(model, client)
    assert model_id in {getattr(model, "model", None), getattr(model, "model_name", None)}


def test_vendor_features_live_in_the_lane_package() -> None:
    assert {route.vendor for route in DEEP_AGENTS_MODEL_ROUTES} == {"anthropic", "openai"}
    assert all(row.id.startswith("deep_agents.") for row in LANE_FEATURES)
    vendor_rows = {row.id for row in AGENT_FEATURES if not row.id.startswith("deep_agents.")}
    assert vendor_rows == {f"{vendor}.{name}" for vendor, name in VENDOR_FEATURES}
    assert ("anthropic", "prompt_caching") in VENDOR_FEATURES
    assert ("openai", "web_search") in VENDOR_FEATURES


# -- OC-R6 review: model identity (item 1) ----------------------------------------------------


def test_the_receipt_states_the_vendor_and_model_id_the_lane_calls() -> None:
    facts = deep_agents_facts()
    agent = canonical_agent("deep_agents", vendor="anthropic")
    _binding, receipt = AuthoredDeepAgentsAdapter().compile(agent, {})
    (model,) = [item for item in receipt.items if item.kind == "model"]
    assert (model.vendor, model.model_id) == ("anthropic", agent.model.model_id)
    # The served definition it materialized stays the item's name and digest.
    assert model.digest == facts.model_profiles[agent.model.profile].ref.digest
    with pytest.raises(ValueError, match="only a model item"):
        MaterializationItem(kind="tool", name="t", verdict="native", vendor="openai")
    # Items without the fields dump as before, so earlier receipts keep their digests.
    plain = MaterializationItem(kind="model", name="m", verdict="native")
    assert "vendor" not in plain.model_dump() and "model_id" not in plain.model_dump()


@pytest.mark.parametrize(
    ("identity", "code"),
    [
        (ServedModel("openai", "claude-haiku-5-5"), "MODEL_PIN_VENDOR_MISMATCH"),
        (ServedModel("anthropic", "claude-sonnet-5-5"), "MODEL_PIN_MODEL_MISMATCH"),
        (None, "MODEL_PIN_UNDECLARED"),
    ],
)
def test_a_served_pin_that_does_not_serve_the_row_refuses_composition(
    identity: ServedModel | None, code: str
) -> None:
    bindings = fixture_bindings()
    digest = bindings.model_profiles["frontier.default"].ref.digest
    catalog = fixture_model_catalog(vendor="anthropic", model_id="claude-haiku-5-5")
    # A production composition: no test flag, so an undeclared digest fails closed too.
    served = replace(
        fixture_served(bindings),
        qualification=False,
        model_identities={} if identity is None else {digest: identity},
    )
    with pytest.raises(ModelPinMismatch) as refused:
        DeepAgentsDeploymentFacts.from_bindings(bindings, served, models=catalog)
    assert refused.value.code == code
    assert refused.value.pointer == "/model_profiles/frontier.default/ref"
    agreeing = replace(
        served, model_identities={digest: ServedModel("anthropic", "claude-haiku-5-5")}
    )
    assert DeepAgentsDeploymentFacts.from_bindings(bindings, agreeing, models=catalog)
    # Only an explicitly flagged test composition may leave a served digest undeclared.
    flagged = replace(served, model_identities={}, qualification=True)
    assert DeepAgentsDeploymentFacts.from_bindings(bindings, flagged, models=catalog)


def test_registered_model_factories_declare_identity_and_never_replace_a_pin() -> None:
    pins = CapabilityPins.load(PINS)
    pinned = pins.models[0].ref.digest
    extra = "sha256:" + "e" * 64

    def factory(_binding: object, _secrets: object) -> object:
        return object()

    with pytest.raises(ValueError, match="MODEL_FACTORY_COLLISION"):
        DeploymentCapabilityComponents(model_factories={pinned: factory}).check_models(pins)
    with pytest.raises(ValueError, match="MODEL_PIN_UNDECLARED"):
        DeploymentCapabilityComponents(model_factories={extra: factory}).check_models(pins)
    DeploymentCapabilityComponents(
        model_factories={extra: factory},
        model_identities={extra: ServedModel("openai", "gpt-5.6-luna")},
    ).check_models(pins)
    DeploymentCapabilityComponents(
        model_factories={pinned: factory}, qualification=True
    ).check_models(pins)
    served = served_components(
        pins,
        get_settings(),
        DeploymentCapabilityComponents(
            model_factories={extra: factory},
            model_identities={extra: ServedModel("openai", "gpt-5.6-luna")},
        ),
    )
    assert served.model_identities[extra] == ServedModel("openai", "gpt-5.6-luna")
    assert all(
        served.model_identities[item.ref.digest] == ServedModel(item.provider, item.model_id)
        for item in pins.models
    )
    assert served.qualification is False


def test_every_served_model_pin_states_vendor_and_model_id() -> None:
    pins = CapabilityPins.load(PINS)
    catalog = checked_in_catalog()
    served = {(item.provider, item.model_id) for item in pins.models}
    # Every installed catalog row has a served definition pinned for exactly its model.
    assert {(catalog.get(p).vendor, catalog.get(p).model_id) for p in catalog.profiles()} <= served


def test_the_worker_factory_refuses_a_binding_sealed_for_another_vendor() -> None:
    binding, _profile, _bundle = exact_fixture()
    sealed = binding.model_copy(
        update={
            "model": binding.model.model_copy(
                update={"provider": "anthropic", "model_name": "claude-haiku-5-5", "settings": {}}
            )
        }
    )
    with pytest.raises(DeepAgentMaterializationError, match="MODEL_PIN_VENDOR_MISMATCH"):
        ExactModelFactory(served_vendor="openai")(sealed, SECRETS)
    with pytest.raises(DeepAgentMaterializationError, match="MODEL_PIN_MODEL_MISMATCH"):
        ExactModelFactory(served_vendor="anthropic", served_model_id="claude-sonnet-5-5")(
            sealed, SECRETS
        )
    exact = ExactModelFactory(served_vendor="anthropic", served_model_id="claude-haiku-5-5")
    assert isinstance(exact(sealed, SECRETS), ChatAnthropic)
    checked = IdentityCheckedModelFactory(
        lambda _b, _s: "built", vendor="anthropic", model_id="claude-sonnet-5-5"
    )
    with pytest.raises(DeepAgentMaterializationError, match="MODEL_PIN_MODEL_MISMATCH"):
        checked(sealed, SECRETS)


# -- OC-R6 review: model tools refused at manifest compile (item 4) ---------------------------


def test_the_lane_checks_its_model_tools_without_a_vendor_vocabulary_in_the_core() -> None:
    checks = LaneOptionsChecks((deep_agents_lane(None),))
    assert checks.profiles() == ("deep_agents",)
    assert checks.check("deep_agents", {"model_tools": {"openai": {"web_search": {}}}}) == ()
    ((pointer, message),) = checks.check(
        "deep_agents", {"model_tools": {"openai": {"todo_list": {}}}}
    )
    assert pointer == "/model_tools/openai/todo_list"
    assert "unknown openai tool 'todo_list'" in message
    ((pointer, _),) = checks.check(
        "deep_agents", {"model_tools": {"openai": {"web_search": {"search_context_size": "x"}}}}
    )
    assert pointer == "/model_tools/openai/web_search"
    assert checks.check("cursor_local", {"model_tools": {"openai": {"todo_list": {}}}}) == ()


@pytest.mark.asyncio
async def test_an_unknown_model_tool_is_a_compile_blocker_at_its_authored_pointer() -> None:
    definitions, search = await fast_track_catalog()
    yaml = MINIMAL.read_text(encoding="utf-8").replace(
        "    lane: deep_agents\n",
        "    lane: deep_agents\n"
        "    provider_options: { deep_agents: { model_tools: { openai: { todo_list: {} } } } }\n",
        1,
    )
    scope = ManifestScope(
        request_scope=SCOPE, actor_id="owner", at=datetime(2026, 10, 8, tzinfo=UTC)
    )
    plain = ManifestCompileService(definitions=definitions, search=search)
    checked = ManifestCompileService(
        definitions=definitions,
        search=search,
        lane_options=LaneOptionsChecks((deep_agents_lane(None),)),
    )
    assert (await plain.compile(yaml, scope)).report.ok  # without the lane: refused at launch
    report = (await checked.compile(yaml, scope)).report
    assert not report.ok
    (blocker,) = [item for item in report.blockers if item.reason == "provider_options_invalid"]
    assert blocker.pointer == (
        "/mission/environment/provider_options/deep_agents/model_tools/openai/todo_list"
    )


def test_equivalent_model_tool_configs_seal_equal_configurations() -> None:
    def sealed(config: dict[str, object]) -> str:
        configuration, _ = resolve_agent_configuration(
            AGENT_FEATURES,
            lane="deep_agents",
            model_provider="openai",
            sandbox_backend="state",
            lane_features=None,
            model_tools={"openai": {"web_search": config}},
        )
        return configuration.configuration_digest

    assert sealed({}) == sealed({"search_context_size": "medium"})
    assert sealed({}) != sealed({"search_context_size": "low"})

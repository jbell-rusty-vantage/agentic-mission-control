"""FIXTURE Model Catalogs (OC-R6) for tests only.

The checked-in installation catalogs are `deployments/<app>/models.toml` (`checked_in_catalog`).
Launch tests bind the fixture profile names the example manifests select (`frontier.*`) to the
WP-CP-040 qualification model, served by deterministic local cognition; their catalog rows carry
that model's vendor and id, so the sealed bindings stay what they were before the catalog existed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from mission_control.application.authoring.manifest_launch_inputs import (
    DeepAgentModelBinding,
    ManifestLaunchBindings,
)
from mission_control.application.resolution.registries import ModelCatalog
from mission_control.bootstrap.model_profiles import compose_model_catalog
from mission_control.domain.execution.contracts import DeepAgentModelComponent
from mission_control.domain.resolution.configuration import Vendor
from mission_control.domain.resolution.profiles import ModelProfile

DEPLOYMENTS = Path(__file__).resolve().parents[2] / "deployments"
FIXTURE_VENDOR: Vendor = "openai"
FIXTURE_MODEL_ID = "fixture-model"


def checked_in_catalog(application_id: str = "biotech") -> ModelCatalog:
    return compose_model_catalog(DEPLOYMENTS, application_id)


def fixture_model_profile(
    profile: str, *, vendor: Vendor = FIXTURE_VENDOR, model_id: str = FIXTURE_MODEL_ID
) -> ModelProfile:
    return ModelProfile(
        profile=profile,
        vendor=vendor,
        model_id=model_id,
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        cost_per_million_input=1.0,
        cost_per_million_output=2.0,
        supports=("structured_output", "tool_use"),
        structured_output="tool_forced",
        # D24: an OpenAI row that uses tools must name the Responses API surface.
        api_surface="responses" if vendor == "openai" else None,
        # The application's ceiling governs fixture missions, as before the catalog existed.
        data_class_ceiling="secret",
    )


def fixture_model_catalog(
    profiles: Iterable[str] = ("frontier.default", "frontier.long_context"),
    *,
    vendor: Vendor = FIXTURE_VENDOR,
    model_id: str = FIXTURE_MODEL_ID,
    rows: Iterable[ModelProfile] = (),
) -> ModelCatalog:
    """A catalog of the named fixture profiles (plus any explicit rows)."""

    extra = tuple(rows)
    named = {row.profile for row in extra}
    return ModelCatalog(
        (
            *(
                fixture_model_profile(name, vendor=vendor, model_id=model_id)
                for name in sorted(set(profiles))
                if name not in named
            ),
            *extra,
        )
    )


def catalog_for(
    components: Mapping[str, DeepAgentModelComponent], *, rows: Iterable[ModelProfile] = ()
) -> ModelCatalog:
    """The catalog that states each component's vendor and model id under its profile name."""

    extra = tuple(rows)
    named = {row.profile for row in extra}
    return ModelCatalog(
        (
            *(
                fixture_model_profile(
                    name, vendor=component.provider, model_id=component.model_name
                )
                for name, component in sorted(components.items())
                if name not in named
            ),
            *extra,
        )
    )


def model_binding(component: DeepAgentModelComponent) -> DeepAgentModelBinding:
    """A Deep Agents model binding: the component's served ref and settings, no vendor."""

    return DeepAgentModelBinding(ref=component.ref, settings=dict(component.settings))


def bindings_catalog(bindings: ManifestLaunchBindings) -> ModelCatalog:
    """The fixture catalog covering every profile the bindings name, on the fixture model."""

    return fixture_model_catalog(bindings.model_profiles)

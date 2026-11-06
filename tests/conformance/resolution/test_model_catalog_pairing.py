"""Resolver conformance over the installed Model Catalogs (OC-R6 / OVE-200).

The checked-in `deployments/<app>/models.toml` carry the PROOFS §6 pins and fallbacks; the
resolver pairs each row's vendor with the lane's declared `model_routes` and refuses an unrouted
pairing (`MODEL_ROUTE_UNSUPPORTED`) at the manifest's `model.profile`, whichever row it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.deep_agents.compile import DEEP_AGENTS_DECLARATION
from mission_control.adapters.deep_agents.routes import DEEP_AGENTS_MODEL_ROUTES
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
)
from mission_control.application.resolution.resolver import MODEL_POINTER, RuntimeResolver
from mission_control.bootstrap.model_profiles import (
    ModelCatalogError,
    compose_model_catalog,
    load_model_catalog_file,
)
from mission_control.domain.resolution.resolved import ResolutionRefused, ResolvedRuntime
from tests.conformance.lanes.compile.stub import NARROW_DECLARATION, STUB_DECLARATION
from tests.conformance.resolution.fixtures import APPLICATIONS
from tests.conformance.resolution.test_resolver_conformance import _registration, _selection
from tests.fixtures.models import DEPLOYMENTS, checked_in_catalog

# PROOFS §6 (OC-D185): role -> (pin, fallback).
PINS = {
    "producer": ("claude-sonnet-5-5", "claude-haiku-5-5"),
    "judge": ("gpt-5.6-terra", "gpt-5.6-luna"),
    "auditor": ("claude-haiku-5-5", "claude-sonnet-5-5"),
    "child": ("claude-haiku-5-5", "gpt-5.6-luna"),
    "probe": ("gpt-5.6-luna", "gpt-5.4-mini"),
}
APPLICATION_IDS = ("ai-engineer", "biotech")


@pytest.mark.parametrize("application_id", APPLICATION_IDS)
def test_each_installed_catalog_carries_the_proofs_pins_and_fallbacks(application_id: str) -> None:
    catalog = compose_model_catalog(DEPLOYMENTS, application_id)
    assert set(catalog.profiles()) == {
        f"{role}.{kind}" for role in PINS for kind in ("default", "fallback")
    }
    for role, (pin, fallback) in PINS.items():
        assert catalog.get(f"{role}.default").model_id == pin
        assert catalog.get(f"{role}.fallback").model_id == fallback
    for profile in catalog.profiles():
        row = catalog.get(profile)
        # Declared, not sentinels: real windows and list prices (models.toml cites the sources).
        assert row.context_window_tokens >= 100_000
        assert row.cost_per_million_input > 0 and row.cost_per_million_output > 0
        assert row.data_class_ceiling == "internal"


def test_the_two_installations_declare_the_same_rows() -> None:
    first, second = (
        load_model_catalog_file(DEPLOYMENTS / app / "models.toml").models for app in APPLICATION_IDS
    )
    assert first == second


def test_the_judge_is_another_vendor_than_the_producer() -> None:
    catalog = checked_in_catalog()
    # Evaluator independence is a vendor fact (design §3, OC-D185), checkable only in data.
    assert catalog.get("judge.default").vendor != catalog.get("producer.default").vendor


def test_deep_agents_routes_every_catalog_vendor_natively() -> None:
    catalog = checked_in_catalog()
    assert DEEP_AGENTS_DECLARATION.model_routes == DEEP_AGENTS_MODEL_ROUTES
    for profile in catalog.profiles():
        route = DEEP_AGENTS_DECLARATION.route(catalog.get(profile).vendor)
        assert route is not None and route.verdict == "native"


@pytest.mark.parametrize("profile", sorted(checked_in_catalog().profiles()))
def test_vendor_pairing_over_the_installed_catalog(profile: str) -> None:
    catalog = checked_in_catalog()
    row = catalog.get(profile)
    lanes = LaneRegistry()
    for declaration in (STUB_DECLARATION, NARROW_DECLARATION):
        lanes.register(_registration(declaration))
    resolver = RuntimeResolver(
        lanes, ApplicationRegistry(APPLICATIONS), catalog, allow_unqualified_lanes=True
    )

    both = resolver.resolve(_selection(vendor=row.vendor, model_profile=profile))
    assert isinstance(both, ResolvedRuntime)
    # The resolved pin is the catalog row, whatever the selection carried.
    assert both.agent.model == row.pin(both.agent.model.settings)

    narrow = resolver.resolve(
        _selection(
            "claude_agent_sdk", vendor=row.vendor, family="StageGraph", model_profile=profile
        )
    )
    route = NARROW_DECLARATION.route(row.vendor)
    assert route is not None
    if route.verdict == "unsupported":
        assert isinstance(narrow, ResolutionRefused)
        assert (narrow.code, narrow.pointer) == ("MODEL_ROUTE_UNSUPPORTED", MODEL_POINTER)
        assert row.vendor in narrow.reason
    else:
        assert isinstance(narrow, ResolvedRuntime)


def test_a_missing_or_invalid_catalog_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ModelCatalogError, match="no model catalog"):
        compose_model_catalog(tmp_path, "biotech")
    target = tmp_path / "biotech"
    target.mkdir()
    source = (DEPLOYMENTS / "biotech" / "models.toml").read_text(encoding="utf-8")
    (target / "models.toml").write_text(
        source.replace('profile = "probe.fallback"', 'profile = "probe.default"'),
        encoding="utf-8",
    )
    with pytest.raises(ModelCatalogError, match="named twice"):
        compose_model_catalog(tmp_path, "biotech")
    (target / "models.toml").write_text(
        source.replace('vendor = "openai"', 'vendor = "mistral"', 1), encoding="utf-8"
    )
    with pytest.raises(ModelCatalogError, match="invalid model catalog"):
        compose_model_catalog(tmp_path, "biotech")


@pytest.mark.parametrize("kind", ["default", "fallback"])
def test_the_judge_is_another_vendor_than_the_producer_for_defaults_and_fallbacks(
    kind: str,
) -> None:
    catalog = checked_in_catalog()
    assert catalog.get(f"judge.{kind}").vendor != catalog.get(f"producer.{kind}").vendor


def test_input_limits_and_long_prompt_tiers_are_declared() -> None:
    catalog = checked_in_catalog()
    limits = {
        "claude-sonnet-5-5": 1_000_000,
        "claude-haiku-5-5": 1_000_000,
        "gpt-5.6-terra": 922_000,
        "gpt-5.6-luna": 922_000,
        "gpt-5.4-mini": 272_000,
    }
    for profile in catalog.profiles():
        row = catalog.get(profile)
        assert row.max_input_tokens == limits[row.model_id]
        assert row.max_input_tokens <= row.context_window_tokens
        tiers = [
            (t.above_input_tokens, t.cost_per_million_input, t.cost_per_million_output)
            for t in row.price_tiers
        ]
        expected = {
            "claude-haiku-5-5": [(100_000, 0.5, 2.5)],
            "gpt-5.6-terra": [(272_000, 4.0, 18.0)],
        }.get(row.model_id, [])
        assert tiers == expected, profile
        # The resolved pin carries both, so a context or cost reader needs no catalog lookup.
        pin = row.pin()
        assert (pin.max_input_tokens, pin.price_tiers) == (row.max_input_tokens, row.price_tiers)


def test_limits_that_contradict_the_window_are_refused() -> None:
    row = checked_in_catalog().get("probe.fallback")
    with pytest.raises(ValueError, match="exceeds context_window_tokens"):
        row.model_validate({**row.model_dump(), "max_input_tokens": 500_000})
    with pytest.raises(ValueError, match="at or above max_input_tokens"):
        row.model_validate(
            {
                **row.model_dump(),
                "price_tiers": [
                    {
                        "above_input_tokens": 272_000,
                        "cost_per_million_input": 1,
                        "cost_per_million_output": 1,
                    }
                ],
            }
        )

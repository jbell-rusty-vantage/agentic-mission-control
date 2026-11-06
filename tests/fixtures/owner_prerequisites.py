"""Owner prerequisite test support (MO-20): a provider-hosted environment binding over the
repository's own `envkits/python-uv-node` kit, sealed with a resolved network policy, the
Secret Broker declarations it names and the kit's base-layer files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from tests.fixtures.environment_kits import kit_pin, published_kit

from mission_control.application.prerequisites import GenerationInputs
from mission_control.domain.authoring.contracts import EnvironmentKitDefinition
from mission_control.domain.authoring.mission_environment import ProviderEnvironmentStrategyName
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy

ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = ROOT / "envkits" / "python-uv-node"
INSTALL = "base/install.sh"
INGRESS = "ingress.mission-control.example"
Provider = Literal["cursor", "anthropic", "openai"]
SECRET_REFS = (
    "GITHUB_READ_TOKEN=secret:github/read_token;setup",
    "SEARCH_API_KEY?=secret:search/api_key;agent",
    "MC_SIGNAL_TOKEN=mint:signal_token;agent",
)


def kit_document(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((KIT_ROOT / "kit.json").read_bytes())
    document.update(changes)
    return document


def install_script() -> bytes:
    return (KIT_ROOT / INSTALL).read_bytes()


def kit_definition(**changes: Any) -> tuple[EnvironmentKitDefinition, str]:
    """The kit as the catalog publishes it, and its exact pin."""

    published = published_kit(kit_document(**changes), (INSTALL, install_script()))
    definition = published.definition
    assert isinstance(definition, EnvironmentKitDefinition)
    return definition, kit_pin(published)


def policy(
    pin: str | None,
    *,
    hosts: tuple[str, ...] = (),
    mode: str = "allowlist",
    ingress: str | None = INGRESS,
) -> ResolvedNetworkPolicy:
    """The resolved policy a binding seals: the kit's egress plus the Signal Ingress host."""

    base = ("files.pythonhosted.org", "pypi.org", "registry.npmjs.org")
    listed = (*base, *hosts, *((ingress,) if ingress else ()))
    return ResolvedNetworkPolicy.model_validate(
        {
            "mode": mode,
            "hosts": tuple(sorted(set(listed))) if mode == "allowlist" else (),
            "signal_ingress": ingress,
            "kit": pin,
        }
    )


def environment_binding(
    pin: str | None,
    network: ResolvedNetworkPolicy | None = None,
    *,
    provider: Provider = "anthropic",
    secret_refs: tuple[str, ...] = SECRET_REFS,
) -> EnvironmentBinding:
    network = network if network is not None else policy(pin)
    return EnvironmentBinding(
        kind="provider_hosted",
        provider=provider,
        environment_ref="env_fixture",
        expected_revision="fixture-1",
        setup_pin=pin,
        network=network,
        network_policy_ref=network.digest,
        secret_refs=secret_refs,
    )


def inputs(
    *,
    strategy: ProviderEnvironmentStrategyName | None = None,
    network: ResolvedNetworkPolicy | None = None,
    provider: Provider = "anthropic",
    **kit_changes: Any,
) -> GenerationInputs:
    definition, pin = kit_definition(**kit_changes)
    return GenerationInputs(
        environment=environment_binding(pin, network, provider=provider),
        kit=definition,
        base_files={INSTALL: install_script()},
        strategy=strategy,
    )


__all__ = [
    "INGRESS",
    "INSTALL",
    "SECRET_REFS",
    "environment_binding",
    "inputs",
    "install_script",
    "kit_definition",
    "kit_document",
    "policy",
]

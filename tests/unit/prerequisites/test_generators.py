"""MO-20: generated paste-ready content for Cursor, Claude, Codex, Managed Agents and OpenAI
Agents items, rendered from the binding's kit and network policy (SPEC-05 sections 1 and 3,
SPEC-06 section 10).

Acceptance "generated content digests match the binding": every item names the binding's kit
pin and network policy digest, its text is what that binding projects (hosts, egress fields,
the pinned base install file, the declared variable names), the same binding renders the same
digests and a changed binding renders different ones. No item carries a secret value.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.environments.network import (
    LaneNetworkContext,
    project_network_policy,
)
from mission_control.application.prerequisites import (
    GENERATED_PROFILES,
    GenerationInputs,
    PrerequisiteGenerationError,
    SecretInGeneratedContent,
    generate_owner_prerequisites,
)
from mission_control.domain.authoring.contracts import EnvironmentKitDefinition
from mission_control.domain.authoring.environment_kits import entrypoint_command
from mission_control.domain.capabilities.bundles import sha256_hex
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import (
    GeneratedFrom,
    OwnerPrerequisite,
    PasteStep,
    VerificationMethod,
)
from tests.fixtures.environment_kits import BASH, kit_pin, published_kit
from tests.fixtures.owner_prerequisites import (
    INGRESS,
    INSTALL,
    environment_binding,
    inputs,
    install_script,
    kit_definition,
    kit_document,
    policy,
)

SUBJECT = "envkit-python-uv-node-1"


def _by_id(prerequisites: tuple[OwnerPrerequisite, ...]) -> dict[str, OwnerPrerequisite]:
    return {item.id: item for item in prerequisites}


def _text(prerequisite: OwnerPrerequisite, name: str) -> str:
    (item,) = [item for item in prerequisite.generated if item.ref.endswith("/" + name)]
    return item.content


def _pasted(prerequisite: OwnerPrerequisite) -> dict[str, str]:
    return {
        step.paste: step.content_ref for step in prerequisite.steps if isinstance(step, PasteStep)
    }


# --------------------------------------------------------------------------- coverage


@pytest.mark.parametrize(
    ("profile", "kwargs", "expected"),
    [
        (
            "claude_cloud",
            {},
            {
                f"claude_cloud.environment.{SUBJECT}": VerificationMethod.PROBE_MISSION,
                "claude_cloud.host.auth_login": VerificationMethod.FILE_CHECK,
            },
        ),
        (
            "codex_cloud",
            {"provider": "openai"},
            {
                f"codex_cloud.environment.{SUBJECT}": VerificationMethod.PROBE_MISSION,
                "codex_cloud.host.codex_login": VerificationMethod.FILE_CHECK,
            },
        ),
        (
            "cursor_cloud",
            {"provider": "cursor", "strategy": "generate"},
            {
                f"cursor_cloud.environment.{SUBJECT}": VerificationMethod.API_PROBE,
                f"cursor_cloud.build_secrets.{SUBJECT}": VerificationMethod.ATTESTATION,
                f"cursor_cloud.secret_store.{SUBJECT}": VerificationMethod.FILE_CHECK,
            },
        ),
        (
            "claude_managed",
            {},
            {
                "claude_managed.webhook.ingress-mission-control-example": (
                    VerificationMethod.PROBE_MISSION
                ),
                f"claude_managed.secret_store.{SUBJECT}": VerificationMethod.FILE_CHECK,
            },
        ),
        (
            "codex_agents",
            {"provider": "openai"},
            {
                "codex_agents.webhook.ingress-mission-control-example": (
                    VerificationMethod.PROBE_MISSION
                ),
                f"codex_agents.secret_store.{SUBJECT}": VerificationMethod.FILE_CHECK,
            },
        ),
    ],
)
def test_each_provider_lane_generates_its_owner_steps(
    profile: str, kwargs: dict[str, Any], expected: dict[str, VerificationMethod]
) -> None:
    prerequisites = generate_owner_prerequisites(profile, inputs(**kwargs))
    assert {item.id: item.verify.method for item in prerequisites} == expected
    for item in prerequisites:
        assert {block.lane for block in item.blocks} == {LaneProfile(profile)}


def test_worker_lanes_and_deep_agents_generate_nothing_here() -> None:
    assert {
        LaneProfile.CURSOR_CLOUD,
        LaneProfile.CLAUDE_CLOUD,
        LaneProfile.CODEX_CLOUD,
        LaneProfile.CLAUDE_MANAGED,
        LaneProfile.CODEX_AGENTS,
    } == GENERATED_PROFILES
    for profile in set(LaneProfile) - GENERATED_PROFILES:
        assert generate_owner_prerequisites(profile, inputs()) == ()


def test_bind_and_sync_strategies_leave_the_environment_to_its_owner_or_the_api() -> None:
    claude = _by_id(generate_owner_prerequisites("claude_cloud", inputs(strategy="bind")))
    assert set(claude) == {"claude_cloud.host.auth_login"}
    codex = _by_id(
        generate_owner_prerequisites("codex_cloud", inputs(strategy="bind", provider="openai"))
    )
    assert set(codex) == {"codex_cloud.host.codex_login"}
    cursor = _by_id(
        generate_owner_prerequisites("cursor_cloud", inputs(strategy="sync", provider="cursor"))
    )
    assert f"cursor_cloud.environment.{SUBJECT}" not in cursor


# --------------------------------------------------------------------------- the binding


def test_generated_content_names_and_matches_the_binding() -> None:
    bound = inputs()
    binding = bound.environment
    assert binding.network is not None and binding.setup_pin is not None
    environment = _by_id(generate_owner_prerequisites("claude_cloud", bound))[
        f"claude_cloud.environment.{SUBJECT}"
    ]
    assert environment.generated_from == GeneratedFrom.of_binding(binding)
    assert environment.generated_from == GeneratedFrom(
        kit=binding.setup_pin, policy_digest=binding.network_policy_ref
    )
    assert set(_pasted(environment)) == {"allowed_domains", "setup_script", "env_vars"}
    # The allowed domains are the binding's resolved hosts, the Signal Ingress host among them.
    assert _text(environment, "domains.txt").splitlines() == list(binding.network.hosts)
    assert INGRESS in binding.network.hosts
    settings = project_network_policy("claude_cloud", binding.network).settings
    assert "Network access: Custom. Include default domains: no." in environment.steps[1]
    assert settings["network_access"] == "Custom"
    # The setup script is the kit's base layer: its packages and the pinned install file.
    setup = _text(environment, "setup.sh")
    assert binding.network_policy_ref is not None
    assert binding.setup_pin in setup and binding.network_policy_ref in setup
    assert "apt-get install -y --no-install-recommends git curl ripgrep jq" in setup
    assert install_script().decode("utf-8").rstrip("\n") in setup
    assert bound.kit is not None
    manifest = {entry.path: entry.digest for entry in bound.kit.file_manifest}
    assert manifest[INSTALL] == "sha256:" + sha256_hex(install_script())
    # Variables are names only: the declared secrets (minted credentials excluded).
    assert _text(environment, "env.template").splitlines() == [
        "GITHUB_READ_TOKEN=",
        "SEARCH_API_KEY=",
    ]
    assert "Optional (may stay empty): SEARCH_API_KEY." in environment.steps


def test_the_same_binding_renders_the_same_digests_and_a_changed_one_does_not() -> None:
    first = generate_owner_prerequisites("codex_cloud", inputs(provider="openai"))
    again = generate_owner_prerequisites("codex_cloud", inputs(provider="openai"))
    assert [item.content_digests for item in first] == [item.content_digests for item in again]
    assert [item.digest for item in first] == [item.digest for item in again]

    wider = policy(kit_definition()[1], hosts=("api.example.org",))
    widened = _by_id(
        generate_owner_prerequisites("codex_cloud", inputs(provider="openai", network=wider))
    )[f"codex_cloud.environment.{SUBJECT}"]
    original = _by_id(first)[f"codex_cloud.environment.{SUBJECT}"]
    assert widened.generated_from is not None and original.generated_from is not None
    assert widened.generated_from.kit == original.generated_from.kit
    assert (
        widened.generated_from.policy_digest
        == wider.digest
        != (original.generated_from.policy_digest)
    )
    assert "api.example.org" in _text(widened, "domains.txt").splitlines()
    # A republished kit (another digest under the same version) renders another setup.
    repackaged = _by_id(
        generate_owner_prerequisites(
            "codex_cloud", inputs(provider="openai", system_packages=["git"])
        )
    )[f"codex_cloud.environment.{SUBJECT}"]
    assert repackaged.id == original.id
    assert repackaged.generated_from != original.generated_from
    assert repackaged.content_digests != original.content_digests


def test_codex_cloud_renders_install_start_skill_and_internet_access() -> None:
    environment = _by_id(generate_owner_prerequisites("codex_cloud", inputs(provider="openai")))[
        f"codex_cloud.environment.{SUBJECT}"
    ]
    assert set(_pasted(environment)) == {
        "install_script",
        "start_skill",
        "env_vars",
        "additional_domains",
    }
    assert entrypoint_command(LaneProfile.CODEX_CLOUD) in _text(environment, "start-skill.md")
    assert "Allow Codex to access internet: on, Custom domains only." in environment.steps

    pin = kit_definition()[1]
    none = policy(pin, mode="none", ingress=None)
    closed = _by_id(
        generate_owner_prerequisites("codex_cloud", inputs(provider="openai", network=none))
    )[f"codex_cloud.environment.{SUBJECT}"]
    assert "Allow Codex to access internet: off." in closed.steps
    assert "additional_domains" not in _pasted(closed)
    open_ = _by_id(
        generate_owner_prerequisites(
            "codex_cloud", inputs(provider="openai", network=policy(pin, mode="allow_all"))
        )
    )[f"codex_cloud.environment.{SUBJECT}"]
    assert "Allow Codex to access internet: on, All (unrestricted)." in open_.steps


def test_cursor_generate_renders_the_environment_fields_the_policy_projects() -> None:
    bound = inputs(provider="cursor", strategy="generate")
    by_id = _by_id(generate_owner_prerequisites("cursor_cloud", bound))
    body = json.loads(_text(by_id[f"cursor_cloud.environment.{SUBJECT}"], "environment.json"))
    assert bound.environment.network is not None
    projection = project_network_policy(
        "cursor_cloud", bound.environment.network, LaneNetworkContext("generate")
    )
    assert {key: body[key] for key in projection.settings} == projection.settings
    assert body["name"] == "mc-python-uv-node-1"
    assert body["start"] == entrypoint_command(LaneProfile.CURSOR_CLOUD)
    assert install_script().decode("utf-8").rstrip("\n") in body["install"]
    # Build Secrets are the setup-phase secrets; the broker store lists every reference.
    assert _text(by_id[f"cursor_cloud.build_secrets.{SUBJECT}"], "build-secrets.txt") == (
        "GITHUB_READ_TOKEN\n"
    )
    assert _text(by_id[f"cursor_cloud.secret_store.{SUBJECT}"], "secret-store.txt") == (
        "secret:github/read_token -> GITHUB_READ_TOKEN (setup)\n"
        "secret:search/api_key -> SEARCH_API_KEY (agent) optional\n"
    )


def test_hosted_agent_webhooks_point_at_the_signal_ingress_host() -> None:
    managed = _by_id(generate_owner_prerequisites("claude_managed", inputs()))
    hook = managed["claude_managed.webhook.ingress-mission-control-example"]
    assert _text(hook, "ingress-mission-control-example.txt") == (
        f"https://{INGRESS}/v1/ingress/provider/anthropic\n"
    )
    agents = _by_id(generate_owner_prerequisites("codex_agents", inputs(provider="openai")))
    openai = agents["codex_agents.webhook.ingress-mission-control-example"]
    assert _text(openai, "ingress-mission-control-example.txt") == (
        f"https://{INGRESS}/v1/ingress/provider/openai\n"
    )
    assert {block.features for block in openai.blocks} == {("observation",)}
    # Without a Signal Ingress host there is no endpoint to register.
    pin = kit_definition()[1]
    quiet = policy(pin, mode="allow_all", ingress=None)
    assert not any(
        item.id.startswith("claude_managed.webhook")
        for item in generate_owner_prerequisites("claude_managed", inputs(network=quiet))
    )


@pytest.mark.skipif(BASH is None, reason="the base layer runs under bash")
def test_every_generated_script_is_valid_bash(tmp_path: Path) -> None:
    scripts: dict[str, str] = {}
    for profile, kwargs in (
        ("claude_cloud", {}),
        ("codex_cloud", {"provider": "openai"}),
        ("cursor_cloud", {"provider": "cursor", "strategy": "generate"}),
    ):
        for item in generate_owner_prerequisites(profile, inputs(**kwargs)):
            for content in item.generated:
                if content.media_type == "text/x-shellscript":
                    scripts[content.ref] = content.content
                elif content.ref.endswith("environment.json"):
                    body = json.loads(content.content)
                    scripts[content.ref + "#install"] = body["install"]
                    scripts[content.ref + "#start"] = body["start"]
    assert len(scripts) == 4
    for ref, text in scripts.items():
        path = tmp_path / "script.sh"
        path.write_bytes(text.encode("utf-8"))
        checked = subprocess.run([str(BASH), "-n", str(path)], capture_output=True, check=False)
        assert checked.returncode == 0, (ref, checked.stderr)


def test_a_binding_without_a_kit_renders_a_default_environment() -> None:
    bare = GenerationInputs(environment=environment_binding(None, secret_refs=()))
    environment = _by_id(generate_owner_prerequisites("claude_cloud", bare))[
        "claude_cloud.environment.default"
    ]
    assert environment.generated_from == GeneratedFrom(
        kit=None, policy_digest=bare.environment.network_policy_ref
    )
    assert "apt-get" not in _text(environment, "setup.sh")
    assert "env_vars" not in _pasted(environment)
    assert "Name: mc-default." in environment.steps[1]


# --------------------------------------------------------------------------- refusals


def test_inputs_must_be_the_kit_and_files_the_binding_pins() -> None:
    definition, pin = kit_definition()
    binding = environment_binding(pin)
    with pytest.raises(PrerequisiteGenerationError, match="setup_pin"):
        GenerationInputs(environment=binding)
    other, _ = kit_definition(version="2")
    with pytest.raises(PrerequisiteGenerationError, match="not envkit.python-uv-node@2"):
        GenerationInputs(environment=binding, kit=other, base_files={INSTALL: install_script()})
    with pytest.raises(PrerequisiteGenerationError, match="needs base/install.sh"):
        GenerationInputs(environment=binding, kit=definition)
    with pytest.raises(PrerequisiteGenerationError, match="not the kit's pinned file"):
        GenerationInputs(
            environment=binding, kit=definition, base_files={INSTALL: b"#!/bin/sh\necho edited\n"}
        )


def test_generated_content_never_carries_a_secret_value() -> None:
    bound = inputs()
    # A value the caller knows to be secret anywhere in a paste block refuses the whole set.
    with pytest.raises(SecretInGeneratedContent, match="setup.sh"):
        generate_owner_prerequisites(
            "claude_cloud", bound, secret_values=["uv python install 3.12"]
        )
    # A minted token in a kit file is refused even when nobody named it.
    leaked = b"#!/usr/bin/env bash\necho mct_" + b"A" * 43 + b"\n"
    published = published_kit(kit_document(), (INSTALL, leaked))
    assert isinstance(published.definition, EnvironmentKitDefinition)
    leaky = GenerationInputs(
        environment=environment_binding(kit_pin(published)),
        kit=published.definition,
        base_files={INSTALL: leaked},
    )
    with pytest.raises(SecretInGeneratedContent, match="setup.sh"):
        generate_owner_prerequisites("claude_cloud", leaky)
    # Every template is names only.
    for profile in GENERATED_PROFILES:
        for item in generate_owner_prerequisites(profile, inputs(strategy="generate")):
            for content in item.generated:
                if content.ref.endswith("env.template"):
                    assert all(line.endswith("=") for line in content.content.splitlines())

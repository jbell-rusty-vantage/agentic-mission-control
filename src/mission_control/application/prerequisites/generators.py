"""Owner prerequisites with generated paste-ready content (materialization-observation SPEC-05
sections 1 and 3, SPEC-06 section 10; ADR-0047).

Each generator renders, from what one lane's binding seals (``mc.environment_binding.v1``: the
Environment Kit pin, the resolved network policy and the Secret Broker declarations) plus the
kit's catalog definition and base-layer files, the human-only steps that lane needs and the
exact text the owner pastes:

* ``cursor_cloud``: under the ``generate`` strategy, the base-layer environment fields
  (``install``, ``start``, ``egressMode``/``egressAllowlist``, C7); the Build Secrets the kit's
  setup phase needs (C6, no API); the broker store the launch ``envVars`` read from;
* ``claude_cloud``: the cloud environment (network level, allowed domains, setup script,
  variable names, A4) and the 30-day ``claude auth login`` on the automation host (A6);
* ``codex_cloud``: the cloud environment (install script, Start skill, variable names, agent
  internet access, X3) and the refreshed ``codex login`` on the worker (X4);
* ``claude_managed`` and ``codex_agents``: the provider webhook endpoint on the Signal Ingress
  host (MA2, OA2) and the broker store the vaults are synced from.

Rendering is pure and deterministic: the same binding, kit and files always yield the same
content digests, and ``generated_from`` names the kit pin and network policy digest they came
from, so a changed binding is detected as drift. Content names variables and secret references
only. A generator receives no secret value, and :func:`screen_generated_content` refuses any
item that carries a minted token or a value the caller knows to be secret.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final

from mission_control.application.environments.network import (
    LaneNetworkContext,
    project_network_policy,
)
from mission_control.application.secrets.commit_scan import SecretInCommit, scan_commit
from mission_control.application.secrets.references import SecretDeclaration, declarations
from mission_control.domain.authoring.contracts import EnvironmentKitDefinition
from mission_control.domain.authoring.environment_kits import entrypoint_command
from mission_control.domain.authoring.mission_environment import ProviderEnvironmentStrategyName
from mission_control.domain.capabilities.bundles import sha256_hex
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy
from mission_control.domain.prerequisites import (
    Freshness,
    GeneratedContent,
    GeneratedFrom,
    LaneBlock,
    OwnerPrerequisite,
    PasteStep,
    PrerequisiteScope,
    Verification,
    VerificationMethod,
)
from mission_control.domain.prerequisites.owner_prerequisites import (
    GeneratedMediaType,
    PrerequisiteProvider,
    PrerequisiteStep,
)

# Provider webhook routes on the Signal Ingress host (SPEC-04 S4, SPEC-06 sections 4 and 5).
PROVIDER_WEBHOOK_PATH: Final = "/v1/ingress/provider/{provider}"
# A6: the claude.ai refresh grant is capped at 30 days (research/claude-code.md Q8 item 6).
CLAUDE_LOGIN_LIFETIME: Final = timedelta(days=30)
# X4: Codex refreshes auth.json when `last_refresh` is about 8 days old (research/codex.md 7.5).
CODEX_LOGIN_REFRESH: Final = timedelta(days=8)
# The SPEC-05 example revalidates a UI-only cloud environment every 30 days.
CLOUD_ENVIRONMENT_REVALIDATION: Final = timedelta(days=30)
ENVIRONMENT_DRIFT: Final = ("kit_digest", "policy_digest")
# The lanes whose per-run secrets the Secret Broker delivers from its store (ADR-0043): the
# Cursor launch `envVars` and the hosted agent API vaults.
BROKER_STORE_PROFILES: Final[frozenset[LaneProfile]] = frozenset(
    {LaneProfile.CURSOR_CLOUD, LaneProfile.CLAUDE_MANAGED, LaneProfile.CODEX_AGENTS}
)


class PrerequisiteGenerationError(ValueError):
    """The inputs cannot render the binding's content (a kit or file that does not match)."""


class SecretInGeneratedContent(ValueError):
    """Generated content would carry a secret value; nothing was generated."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"refused to generate a secret value in {ref}")
        self.ref = ref


@dataclass(frozen=True)
class PrerequisiteEnvironment:
    """Declared inputs for preflight, before a provider environment has been created.

    This is not an execution binding and cannot authorize a launch.
    """

    setup_pin: str | None = None
    network_policy_ref: str | None = None
    network: ResolvedNetworkPolicy | None = None
    secret_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationInputs:
    """What one lane binds: its environment binding, the Environment Kit definition its
    ``setup_pin`` resolves to, the kit bundle's base-layer files (verified against the kit's
    file manifest) and, for a provider-hosted base layer, the environment strategy."""

    environment: EnvironmentBinding | PrerequisiteEnvironment
    kit: EnvironmentKitDefinition | None = None
    base_files: Mapping[str, bytes] = field(default_factory=dict)
    strategy: ProviderEnvironmentStrategyName | None = None

    def __post_init__(self) -> None:
        pin = self.environment.setup_pin
        if (pin is None) != (self.kit is None):
            raise PrerequisiteGenerationError(
                "the Environment Kit definition is the one the binding's setup_pin pins"
            )
        if self.kit is None or pin is None:
            return
        parsed = CapabilityPin.parse(pin)
        if (parsed.capability_id, parsed.version) != (self.kit.kit.id, self.kit.kit.version):
            raise PrerequisiteGenerationError(
                f"the binding pins {pin}, not {self.kit.kit.id}@{self.kit.kit.version}"
            )
        manifest = {entry.path: entry.digest for entry in self.kit.file_manifest}
        for path, content in self.base_files.items():
            if manifest.get(path) != "sha256:" + sha256_hex(content):
                raise PrerequisiteGenerationError(f"{path} is not the kit's pinned file")
        needed = [
            path
            for path in (
                self.kit.kit.base.install,
                *(service.start for service in self.kit.kit.base.services),
            )
            if path is not None and path not in self.base_files
        ]
        if needed:
            raise PrerequisiteGenerationError(
                f"the kit's base layer needs {', '.join(needed)} to render"
            )

    @property
    def generated_from(self) -> GeneratedFrom:
        return GeneratedFrom(
            kit=self.environment.setup_pin, policy_digest=self.environment.network_policy_ref
        )

    @property
    def policy(self) -> ResolvedNetworkPolicy | None:
        return self.environment.network

    @property
    def subject(self) -> str:
        """The prerequisite id segment: the kit id and version, or ``default``."""

        if self.kit is None:
            return "default"
        kit_id = self.kit.kit.id.replace(".", "-")
        return f"{kit_id}-{self.kit.kit.version}".lower().replace(".", "-").replace("+", "-")

    @property
    def environment_name(self) -> str:
        """The provider environment the owner creates for this kit (``mc-<kit>-<version>``)."""

        return "mc-" + self.subject.removeprefix("envkit-")

    @property
    def secrets(self) -> tuple[SecretDeclaration, ...]:
        """The declarations whose values the owner provides (minted credentials excluded)."""

        return tuple(
            item for item in declarations(self.environment.secret_refs) if item.ref.scheme != "mint"
        )

    @property
    def variable_names(self) -> tuple[str, ...]:
        """Every environment variable the owner names in a provider environment."""

        kit_variables = () if self.kit is None else self.kit.kit.requires.variables
        return tuple(sorted({*kit_variables, *(item.name for item in self.secrets)}))

    def file_text(self, path: str) -> str:
        return self.base_files[path].decode("utf-8")


# --- shared renderers -----------------------------------------------------------------------


def _ref(profile: LaneProfile, inputs: GenerationInputs, name: str) -> str:
    return f"generated/{profile.value.replace('_', '-')}/{inputs.subject}/{name}"


def _content(ref: str, media_type: GeneratedMediaType, text: str) -> GeneratedContent:
    return GeneratedContent.render(ref, media_type, text if text.endswith("\n") else text + "\n")


def _origin(inputs: GenerationInputs) -> str:
    kit = inputs.environment.setup_pin or "no Environment Kit"
    policy = inputs.environment.network_policy_ref or "no network policy"
    return f"{kit}; network policy {policy}"


def _embedded(path: str, text: str) -> str:
    """A bundle file run inline through a quoted heredoc, so the shell expands nothing."""

    body = text.rstrip("\n")
    delimiter = "MC_" + sha256_hex(f"{path}\n{body}".encode())[:12].upper()
    return f"# {path}\nbash <<'{delimiter}'\n{body}\n{delimiter}"


def _setup_script(profile: LaneProfile, inputs: GenerationInputs) -> str:
    """The base layer: system packages and the kit's base install script."""

    lines = [
        "#!/usr/bin/env bash",
        f"# Base layer for {profile.value}, rendered by Mission Control from {_origin(inputs)}.",
        "# It names variables only and never contains a secret value. Regenerated when the kit",
        "# or the network policy changes; paste it unchanged.",
        "set -euo pipefail",
    ]
    kit = None if inputs.kit is None else inputs.kit.kit
    if kit is not None and kit.system_packages:
        packages = " ".join(kit.system_packages)
        lines += [
            "if command -v apt-get >/dev/null 2>&1; then",
            "    apt-get update",
            f"    apt-get install -y --no-install-recommends {packages}",
            "fi",
        ]
    if kit is not None and kit.toolchains:
        declared = ", ".join(
            f"{name} {version}" for name, version in sorted(kit.toolchains.items())
        )
        lines.append(f"# Declared toolchains (the mission layer receipt records them): {declared}")
    if kit is not None and kit.base.install is not None:
        lines.append(_embedded(kit.base.install, inputs.file_text(kit.base.install)))
    return "\n".join(lines)


def _start_commands(profile: LaneProfile, inputs: GenerationInputs) -> list[str]:
    """The kit's long-lived services, then the bootstrap entrypoint (SPEC-01 section 1)."""

    services = () if inputs.kit is None else inputs.kit.kit.base.services
    commands = [_embedded(service.start, inputs.file_text(service.start)) for service in services]
    return [*commands, entrypoint_command(profile)]


def _variables_template(inputs: GenerationInputs) -> str:
    return "\n".join(f"{name}=" for name in inputs.variable_names)


def _domains(policy: ResolvedNetworkPolicy) -> str:
    return "\n".join(policy.hosts)


def _optional_note(inputs: GenerationInputs) -> tuple[str, ...]:
    optional = sorted(item.name for item in inputs.secrets if not item.required)
    if not optional:
        return ()
    return (f"Optional (may stay empty): {', '.join(optional)}.",)


def _lane(profile: LaneProfile) -> tuple[LaneBlock, ...]:
    return (LaneBlock(lane=profile),)


def _attest(prerequisite_id: str, value: str) -> str:
    return (
        f"Record the public identifier ({value}) for {prerequisite_id} in missionctl setup. "
        "The scoped wizard includes the current definition digest; never enter credentials here."
    )


# --- per-lane items -------------------------------------------------------------------------


def _broker_store(profile: LaneProfile, inputs: GenerationInputs) -> OwnerPrerequisite | None:
    """M4: the Secret Broker store holds every value the binding's declarations name."""

    secrets = inputs.secrets
    if not secrets:
        return None
    prerequisite_id = f"{profile.value}.secret_store.{inputs.subject}"
    ref = _ref(profile, inputs, "secret-store.txt")
    listing = "\n".join(
        f"{item.ref} -> {item.name} ({', '.join(item.phases)})"
        + ("" if item.required else " optional")
        for item in sorted(secrets, key=lambda item: str(item.ref))
    )
    return OwnerPrerequisite(
        id=prerequisite_id,
        provider="mission_control",
        scope=PrerequisiteScope.HOST,
        title=f"Store the secrets {profile.value} needs in the Secret Broker",
        why=(
            f"{profile.value} receives its secrets from the Secret Broker per run; the store "
            "must hold a value for every reference the binding declares."
        ),
        blocks=_lane(profile),
        steps=(
            "Add a value for each reference below to the Secret Broker store on the Mission "
            "Control host (environment: references come from the worker's environment).",
            PasteStep(paste="secret_references", content_ref=ref),
            *_optional_note(inputs),
        ),
        verify=Verification(
            method=VerificationMethod.FILE_CHECK, probe="secret-broker-store: names only"
        ),
        generated_from=inputs.generated_from,
        generated=(_content(ref, "text/plain", listing),),
    )


def _cursor_cloud(inputs: GenerationInputs) -> list[OwnerPrerequisite]:
    profile = LaneProfile.CURSOR_CLOUD
    items: list[OwnerPrerequisite] = []
    policy = inputs.policy
    if inputs.strategy == "generate":
        prerequisite_id = f"cursor_cloud.environment.{inputs.subject}"
        ref = _ref(profile, inputs, "environment.json")
        body: dict[str, object] = {
            "name": inputs.environment_name,
            "install": _setup_script(profile, inputs),
            "start": "\n".join(_start_commands(profile, inputs)),
        }
        if policy is not None:
            projection = project_network_policy(profile, policy, LaneNetworkContext("generate"))
            body |= projection.settings
        items.append(
            OwnerPrerequisite(
                id=prerequisite_id,
                provider="cursor",
                scope=PrerequisiteScope.ENVIRONMENT,
                title=f"Create the Cursor cloud environment '{inputs.environment_name}'",
                why=(
                    "The generate strategy leaves the base-layer environment to the owner; its "
                    "install, start and egress fields must be exactly the generated ones."
                ),
                blocks=_lane(profile),
                steps=(
                    "Open the Cursor Dashboard -> Cloud Agents -> Environments and create (or "
                    f"update) '{inputs.environment_name}'.",
                    PasteStep(paste="environment_json", content_ref=ref),
                    "Wait for the first Build to succeed.",
                ),
                verify=Verification(
                    method=VerificationMethod.API_PROBE, probe="cursor: GET /v1/environments"
                ),
                freshness=Freshness(on_change_of=ENVIRONMENT_DRIFT),
                generated_from=inputs.generated_from,
                generated=(_content(ref, "application/json", json.dumps(body, indent=2)),),
            )
        )
    build = sorted(item.name for item in inputs.secrets if "setup" in item.phases)
    if build:
        prerequisite_id = f"cursor_cloud.build_secrets.{inputs.subject}"
        ref = _ref(profile, inputs, "build-secrets.txt")
        items.append(
            OwnerPrerequisite(
                id=prerequisite_id,
                provider="cursor",
                scope=PrerequisiteScope.ENVIRONMENT,
                title="Add the Build Secrets the kit's setup needs",
                why="Cursor Build Secrets have no API; the setup phase reads these names.",
                blocks=_lane(profile),
                steps=(
                    "Open the Cursor Dashboard -> Cloud Agents -> Build Secrets and add each "
                    "name below with its value.",
                    PasteStep(paste="build_secret_names", content_ref=ref),
                    "Trigger a Build and confirm it succeeds.",
                    _attest(prerequisite_id, "<build id>"),
                ),
                verify=Verification(method=VerificationMethod.ATTESTATION),
                freshness=Freshness(on_change_of=("kit_digest",)),
                generated_from=inputs.generated_from,
                generated=(_content(ref, "text/plain", "\n".join(build)),),
            )
        )
    return items


def _claude_cloud(inputs: GenerationInputs) -> list[OwnerPrerequisite]:
    profile = LaneProfile.CLAUDE_CLOUD
    items: list[OwnerPrerequisite] = []
    if inputs.strategy != "bind":
        items.append(_claude_cloud_environment(inputs))
    items.append(
        OwnerPrerequisite(
            id="claude_cloud.host.auth_login",
            provider="anthropic",
            scope=PrerequisiteScope.HOST,
            title="Sign in with 'claude auth login' on the automation host",
            why=(
                "Cloud session control needs an interactive claude.ai login; the refresh grant "
                "is capped at 30 days and setup-token does not carry session control."
            ),
            blocks=_lane(profile),
            steps=(
                "On the automation host run: claude auth login (with the claude.ai account "
                "that owns the cloud environment).",
                "Repeat before the login expires; Mission Control flags it 7 days ahead.",
            ),
            verify=Verification(
                method=VerificationMethod.FILE_CHECK, probe="claude auth status on the host"
            ),
            freshness=Freshness(expires_after=CLAUDE_LOGIN_LIFETIME),
        )
    )
    return items


def _claude_cloud_environment(inputs: GenerationInputs) -> OwnerPrerequisite:
    profile = LaneProfile.CLAUDE_CLOUD
    prerequisite_id = f"claude_cloud.environment.{inputs.subject}"
    generated: list[GeneratedContent] = []
    steps: list[PrerequisiteStep] = [
        "Open claude.ai/code -> environment selector -> New environment (Team and Enterprise "
        "owners: admin page Cloud environments for a shared one).",
    ]
    policy = inputs.policy
    level = "Trusted"
    if policy is not None:
        settings = project_network_policy(profile, policy).settings
        level = str(settings["network_access"])
    steps.append(
        f"Name: {inputs.environment_name}. Network access: {level}."
        + (" Include default domains: no." if level == "Custom" else "")
    )
    if policy is not None and policy.mode == "allowlist":
        ref = _ref(profile, inputs, "domains.txt")
        generated.append(_content(ref, "text/plain", _domains(policy)))
        steps.append(PasteStep(paste="allowed_domains", content_ref=ref))
    ref = _ref(profile, inputs, "setup.sh")
    generated.append(_content(ref, "text/x-shellscript", _setup_script(profile, inputs)))
    steps.append(PasteStep(paste="setup_script", content_ref=ref))
    if inputs.variable_names:
        ref = _ref(profile, inputs, "env.template")
        generated.append(_content(ref, "text/plain", _variables_template(inputs)))
        steps += [
            PasteStep(paste="env_vars", content_ref=ref),
            "Fill each value in the environment dialog (anyone using the environment can read "
            "them).",
            *_optional_note(inputs),
        ]
    steps.append("Copy the environment id (env_...). " + _attest(prerequisite_id, "env_..."))
    return OwnerPrerequisite(
        id=prerequisite_id,
        provider="anthropic",
        scope=PrerequisiteScope.ENVIRONMENT,
        title=f"Create the Claude Code cloud environment '{inputs.environment_name}'",
        why="Claude cloud environments are UI-only; the lane needs this base layer.",
        blocks=_lane(profile),
        steps=tuple(steps),
        verify=Verification(
            method=VerificationMethod.PROBE_MISSION, probe="missions/probes/claude-cloud-env@1"
        ),
        freshness=Freshness(
            revalidate_after=CLOUD_ENVIRONMENT_REVALIDATION, on_change_of=ENVIRONMENT_DRIFT
        ),
        generated_from=inputs.generated_from,
        generated=tuple(generated),
    )


def _codex_cloud(inputs: GenerationInputs) -> list[OwnerPrerequisite]:
    profile = LaneProfile.CODEX_CLOUD
    items: list[OwnerPrerequisite] = []
    if inputs.strategy != "bind":
        items.append(_codex_cloud_environment(inputs))
    items.append(
        OwnerPrerequisite(
            id="codex_cloud.host.codex_login",
            provider="openai",
            scope=PrerequisiteScope.HOST,
            title="Sign in with 'codex login' on the worker and keep auth.json refreshed",
            why="Codex cloud requires signing in with ChatGPT; API keys cannot launch it.",
            blocks=_lane(profile),
            steps=(
                "On the worker run: codex login (or codex login --device-auth).",
                "Keep the refreshed auth.json; Codex refreshes it after about 8 days.",
            ),
            verify=Verification(
                method=VerificationMethod.FILE_CHECK, probe="codex login status on the worker"
            ),
            freshness=Freshness(revalidate_after=CODEX_LOGIN_REFRESH),
        )
    )
    return items


def _codex_cloud_environment(inputs: GenerationInputs) -> OwnerPrerequisite:
    profile = LaneProfile.CODEX_CLOUD
    prerequisite_id = f"codex_cloud.environment.{inputs.subject}"
    install = _ref(profile, inputs, "install.sh")
    start = _ref(profile, inputs, "start-skill.md")
    start_skill = "\n".join(
        [
            f"# Start {inputs.environment_name}",
            "",
            "Run before agent work: start the kit's services, then the Mission Control "
            "bootstrap entrypoint.",
            "",
            "```bash",
            *_start_commands(profile, inputs),
            "```",
        ]
    )
    generated = [
        _content(install, "text/x-shellscript", _setup_script(profile, inputs)),
        _content(start, "text/markdown", start_skill),
    ]
    steps: list[PrerequisiteStep] = [
        "Open Codex (web or desktop) -> Work in -> Cloud -> Create environment, and select the "
        "mission's GitHub repositories.",
        f"Name: {inputs.environment_name}.",
        PasteStep(paste="install_script", content_ref=install),
        PasteStep(paste="start_skill", content_ref=start),
    ]
    if inputs.variable_names:
        ref = _ref(profile, inputs, "env.template")
        generated.append(_content(ref, "text/plain", _variables_template(inputs)))
        steps += [
            PasteStep(paste="env_vars", content_ref=ref),
            "Fill each value as an environment variable or a network secret.",
            *_optional_note(inputs),
        ]
    policy = inputs.policy
    if policy is not None:
        settings = project_network_policy(profile, policy).settings
        if not settings["agent_internet_access"]:
            steps.append("Allow Codex to access internet: off.")
        elif settings.get("domain_allowlist") == "all":
            steps.append("Allow Codex to access internet: on, All (unrestricted).")
        else:
            ref = _ref(profile, inputs, "domains.txt")
            generated.append(_content(ref, "text/plain", _domains(policy)))
            steps += [
                "Allow Codex to access internet: on, Custom domains only.",
                PasteStep(paste="additional_domains", content_ref=ref),
            ]
    steps += [
        "Test the environment, then Publish (every later edit needs a Republish).",
        "Copy the ENV_ID (codex cloud picker or codex cloud list --json). "
        + _attest(prerequisite_id, "<ENV_ID>"),
    ]
    return OwnerPrerequisite(
        id=prerequisite_id,
        provider="openai",
        scope=PrerequisiteScope.ENVIRONMENT,
        title=f"Create and publish the Codex cloud environment '{inputs.environment_name}'",
        why="Codex cloud environments are created and published in the UI only.",
        blocks=_lane(profile),
        steps=tuple(steps),
        verify=Verification(
            method=VerificationMethod.PROBE_MISSION, probe="missions/probes/codex-cloud-env@1"
        ),
        freshness=Freshness(
            revalidate_after=CLOUD_ENVIRONMENT_REVALIDATION, on_change_of=ENVIRONMENT_DRIFT
        ),
        generated_from=inputs.generated_from,
        generated=tuple(generated),
    )


def _webhook(
    profile: LaneProfile,
    inputs: GenerationInputs,
    *,
    provider: PrerequisiteProvider,
    console: str,
) -> OwnerPrerequisite | None:
    """MA2 / OA2: the provider pushes session events to the Signal Ingress host."""

    policy = inputs.policy
    host = None if policy is None else policy.signal_ingress
    if host is None:
        return None
    subject = host.replace(".", "-")
    prerequisite_id = f"{profile.value}.webhook.{subject}"
    ref = f"generated/{profile.value.replace('_', '-')}/webhook/{subject}.txt"
    url = "https://" + host + PROVIDER_WEBHOOK_PATH.format(provider=provider)
    return OwnerPrerequisite(
        id=prerequisite_id,
        provider=provider,
        scope=PrerequisiteScope.ACCOUNT,
        title=f"Register the {profile.value} webhook endpoint",
        why="Provider webhooks wake Mission Control; they are evidence, never authority.",
        blocks=(LaneBlock(lane=profile, features=("observation",)),),
        steps=(
            f"Open {console} and add an endpoint with this URL.",
            PasteStep(paste="endpoint_url", content_ref=ref),
            "Store the endpoint's signing secret in the Secret Broker store (Mission Control "
            "never renders its value).",
        ),
        verify=Verification(
            method=VerificationMethod.PROBE_MISSION,
            probe=f"missions/probes/{profile.value.replace('_', '-')}-webhook@1",
        ),
        generated_from=GeneratedFrom(),
        generated=(_content(ref, "text/plain", url),),
    )


def _claude_managed(inputs: GenerationInputs) -> list[OwnerPrerequisite | None]:
    profile = LaneProfile.CLAUDE_MANAGED
    console = "the Claude Console -> Webhooks"
    return [_webhook(profile, inputs, provider="anthropic", console=console)]


def _codex_agents(inputs: GenerationInputs) -> list[OwnerPrerequisite | None]:
    profile = LaneProfile.CODEX_AGENTS
    console = "the OpenAI platform project -> Webhooks"
    return [_webhook(profile, inputs, provider="openai", console=console)]


_GENERATORS: Final[
    Mapping[LaneProfile, Callable[[GenerationInputs], Iterable[OwnerPrerequisite | None]]]
] = {
    LaneProfile.CURSOR_CLOUD: _cursor_cloud,
    LaneProfile.CLAUDE_CLOUD: _claude_cloud,
    LaneProfile.CODEX_CLOUD: _codex_cloud,
    LaneProfile.CLAUDE_MANAGED: _claude_managed,
    LaneProfile.CODEX_AGENTS: _codex_agents,
}
GENERATED_PROFILES: Final[frozenset[LaneProfile]] = frozenset(_GENERATORS)


def screen_generated_content(
    prerequisites: Iterable[OwnerPrerequisite], *, secret_values: Iterable[str] = ()
) -> None:
    """Raise :class:`SecretInGeneratedContent` for the first item carrying a minted token or
    one of ``secret_values`` (the Secret Broker's commit scan, applied to paste blocks)."""

    files = [
        (item.ref, item.content.encode("utf-8"))
        for prerequisite in prerequisites
        for item in prerequisite.generated
    ]
    try:
        scan_commit(files, secret_values=secret_values)
    except SecretInCommit as error:
        raise SecretInGeneratedContent(error.location) from None


def generate_owner_prerequisites(
    profile: LaneProfile | str,
    inputs: GenerationInputs,
    *,
    secret_values: Iterable[str] = (),
) -> tuple[OwnerPrerequisite, ...]:
    """The owner prerequisites ``profile`` needs for ``inputs``, with their generated content.

    A worker-hosted lane needs none from here (its host prerequisites are the worker runbook's,
    MO-08); Deep Agents needs none."""

    profile = LaneProfile(profile)
    generator = _GENERATORS.get(profile)
    if generator is None:
        return ()
    items = [item for item in generator(inputs) if item is not None]
    if profile in BROKER_STORE_PROFILES and (store := _broker_store(profile, inputs)) is not None:
        items.append(store)
    prerequisites = tuple(items)
    screen_generated_content(prerequisites, secret_values=secret_values)
    return prerequisites


__all__ = [
    "BROKER_STORE_PROFILES",
    "CLAUDE_LOGIN_LIFETIME",
    "CODEX_LOGIN_REFRESH",
    "GENERATED_PROFILES",
    "PROVIDER_WEBHOOK_PATH",
    "GenerationInputs",
    "PrerequisiteGenerationError",
    "SecretInGeneratedContent",
    "generate_owner_prerequisites",
    "screen_generated_content",
]

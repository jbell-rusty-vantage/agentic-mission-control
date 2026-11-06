"""The ``mission/v2`` environment additions (materialization SPEC-01 §3): Environment Kit pin,
variables, secrets, network, git and provider environment strategy.

The shapes here are the authoring surface only. Values stay non-secret: ``variables[].value``
is inline and public, ``value_ref`` names installation configuration resolved at compile, and
``secrets[].ref`` names a Secret Broker source or a per-run minted credential, never a value.
Three rule families are pure and live here:

- **lane rules** (:func:`environment_lane_issues`): which strategies a lane offers, what a
  strategy needs, and the cross-field agreements (kit pin and setup pin, git target and
  workspace repo, network mode and hosts), checked on the merged environment so an overlay
  never fails the merge itself;
- **inheritance** (:func:`environment_narrowing_issues`): a child may not widen
  ``network`` (directly or by unsetting it), add secrets beyond the parent's grant or relax
  or unset ``git.write``; switching the kit whose egress the policy includes is compared host
  by host once both kits resolve (:func:`kit_switch_issues`, at compile admission);
- **kit requirements** (:func:`kit_requirement_issues`): a resolved kit's ``requires`` must be
  satisfied by the declared variables, secrets, egress and git repositories.

Resolving a kit pin or a ``config:`` reference is the compile service's job (a port), and
resolving the network policy into hosts is ``domain.execution.network_policy``'s; nothing here
contacts a provider, a catalog or the installation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from mission_control.domain.authoring.manifest import (
    PIN_PATTERN,
    ManifestErrorCode,
    ManifestIssue,
    ManifestModel,
    _issue,
)
from mission_control.domain.capabilities.host_support import LaneProfile

ENVIRONMENT_NAME_PATTERN: Final = r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"
# A `config:` reference names one installation configuration key (`CONFIG_KEY_PATTERN`).
CONFIG_KEY_PATTERN: Final = r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,255}$"
CONFIG_REF_PATTERN: Final = r"^config:" + CONFIG_KEY_PATTERN.removeprefix("^")
# Installation configuration is non-secret: a key naming a credential is never configuration
# (it belongs in `secrets[]`), refused where configuration loads and where compile admits it.
SECRET_LIKE_CONFIG_KEY_PATTERN: Final = r"(?i)(key|token|secret|password|passwd|dsn|credential)"  # noqa: S105 - a pattern
# Per-run credentials Mission Control mints (SPEC-04 owns their issuance).
MINTED_CREDENTIALS: Final = ("signal_token",)
SECRET_REF_PATTERN: Final = (
    r"^(?:secret:[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}"
    r"|mint:(?:" + "|".join(MINTED_CREDENTIALS) + r"))$"
)
# What `mc.environment_binding.v1` records per secret: the Secret Broker's declaration entry
# `NAME[?]=<ref>[;phase,...]` (ADR-0043; `application/secrets/references.py`), `?` marking an
# optional secret and absent phases meaning both. Besides the manifest's references a
# deployment binding may name `vault:<path>` or `environment:<NAME>`; never a value.
BINDING_SECRET_REF_PATTERN: Final = (
    ENVIRONMENT_NAME_PATTERN.removesuffix("$")
    + r"\??=(?:"
    + SECRET_REF_PATTERN.removeprefix("^").removesuffix("$")
    + r"|vault:[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}"
    + r"|environment:[A-Za-z_][A-Za-z0-9_]{0,127})"
    + r"(?:;(?:setup|agent)(?:,(?:setup|agent))?)?$"
)
# A host name, optionally a leading `*.` wildcard; never a URL, port or path.
EGRESS_HOST_PATTERN: Final = (
    r"^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
REPOSITORY_URL_PATTERN: Final = r"^(?:https://|ssh://|git@)\S+$"
MISSION_BRANCH_PATTERN: Final = r"^mc/\{run\}/[A-Za-z0-9{}._/-]*$"

EnvironmentName = Annotated[str, StringConstraints(pattern=ENVIRONMENT_NAME_PATTERN)]
RepositoryUrl = Annotated[str, StringConstraints(pattern=REPOSITORY_URL_PATTERN)]
EgressHost = Annotated[str, StringConstraints(pattern=EGRESS_HOST_PATTERN, max_length=253)]
NetworkMode = Literal["allow_all", "allowlist", "none"]
SecretPhase = Literal["setup", "agent"]
RepositoryRole = Literal["target", "dependency", "knowledge"]
GitWriteMode = Literal["none", "branch", "branch_and_pr"]
PullRequestMode = Literal["mission_control", "provider"]
ProviderEnvironmentStrategyName = Literal["bind", "sync", "generate"]

# Authority order: a child may move down these ladders, never up.
NETWORK_MODE_RANK: Final[Mapping[str, int]] = {"none": 0, "allowlist": 1, "allow_all": 2}
GIT_WRITE_RANK: Final[Mapping[str, int]] = {"none": 0, "branch": 1, "branch_and_pr": 2}

# SPEC-01 §7: `sync` needs a provider environments API (Cursor only); `generate` renders an
# owner prerequisite; `bind` uses an existing provider environment. Worker lanes have none.
PROVIDER_ENVIRONMENT_STRATEGIES: Final[Mapping[LaneProfile, frozenset[str]]] = {
    LaneProfile.CURSOR_CLOUD: frozenset({"bind", "sync", "generate"}),
    LaneProfile.CLAUDE_CLOUD: frozenset({"bind", "generate"}),
    LaneProfile.CODEX_CLOUD: frozenset({"bind", "generate"}),
}
# The fields this module adds to a mission/v2 Environment.
ENVIRONMENT_ADDITIONS: Final = (
    "kit",
    "variables",
    "secrets",
    "network",
    "git",
    "provider_environment",
)


class KitSelection(ManifestModel):
    """The Environment Kit a lane materializes: an exact catalog pin, digest required."""

    pin: str = Field(pattern=PIN_PATTERN, max_length=512)

    @model_validator(mode="after")
    def _exact(self) -> KitSelection:
        if "#sha256:" not in self.pin:
            raise ValueError("an environment kit pin is exact: id@version#sha256:<digest>")
        return self


class EnvironmentVariable(ManifestModel):
    """A non-secret variable: an inline ``value`` or a ``config:`` installation reference."""

    # Exactly one source is a string: an explicit null counts as absent, as `_one_source` has it.
    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {"required": ["value"], "properties": {"value": {"type": "string"}}},
                {"required": ["value_ref"], "properties": {"value_ref": {"type": "string"}}},
            ]
        }
    )

    name: EnvironmentName
    value: str | None = Field(default=None, max_length=4_096)
    value_ref: str | None = Field(default=None, pattern=CONFIG_REF_PATTERN)

    @model_validator(mode="after")
    def _one_source(self) -> EnvironmentVariable:
        if (self.value is None) == (self.value_ref is None):
            raise ValueError("a variable needs exactly one of value | value_ref")
        return self

    @property
    def config_key(self) -> str | None:
        return self.value_ref.removeprefix("config:") if self.value_ref is not None else None


class EnvironmentSecret(ManifestModel):
    """A secret by name and broker reference; the value never enters the manifest."""

    name: EnvironmentName
    ref: str = Field(pattern=SECRET_REF_PATTERN)
    phases: tuple[SecretPhase, ...] = Field(default=("agent",), min_length=1)

    @model_validator(mode="after")
    def _unique_phases(self) -> EnvironmentSecret:
        if len(set(self.phases)) != len(self.phases):
            raise ValueError("secret phases must not repeat")
        return self

    @property
    def binding_ref(self) -> str:
        """The ``NAME=ref[;phase,...]`` entry an Environment Binding records (names and refs
        only); the phases are left out when the secret reaches both, as the broker reads it."""

        phases = "" if set(self.phases) == {"setup", "agent"} else ";" + ",".join(self.phases)
        return f"{self.name}={self.ref}{phases}"


class NetworkPolicy(ManifestModel):
    """The declared egress policy. ``include_kit`` adds the kit's required egress and
    ``include_signal_ingress`` the Mission Control ingress host (SPEC-04).

    A node overlay merges into the inherited policy, so cross-field rules are validation
    issues on the effective environment (:func:`environment_lane_issues`), not shape errors."""

    mode: NetworkMode = "allowlist"
    allow: tuple[EgressHost, ...] = ()
    include_kit: bool = True
    include_signal_ingress: bool = False

    @model_validator(mode="after")
    def _unique_hosts(self) -> NetworkPolicy:
        if len(set(self.allow)) != len(self.allow):
            raise ValueError("network.allow must not repeat hosts")
        return self

    def allows(self, host: str) -> bool:
        """Whether this policy's own entries admit ``host`` (exact or ``*.`` suffix)."""

        if self.mode == "allow_all":
            return True
        if self.mode == "none":
            return False
        return any(host_covers(entry, host) for entry in self.allow)


class GitRepository(ManifestModel):
    url: RepositoryUrl
    ref: str | None = Field(default=None, min_length=1, max_length=256)
    role: RepositoryRole
    access: Literal["read", "write"] | None = None

    @model_validator(mode="after")
    def _dependency_is_read_only(self) -> GitRepository:
        if self.role == "dependency" and self.access == "write":
            raise ValueError("a dependency repository is read-only")
        return self


class GitPullRequest(ManifestModel):
    draft: bool = True
    base: str | None = Field(default=None, min_length=1, max_length=256)
    # `mission_control` opens the PR as a governed `repo_pr` effect; `provider` records the
    # provider's own auto-PR as an observed artifact (cloud lanes, SPEC-01 §6).
    mode: PullRequestMode = "mission_control"


class GitWrite(ManifestModel):
    mode: GitWriteMode = "branch"
    branch: str = Field(default="mc/{run}/{unit}", pattern=MISSION_BRANCH_PATTERN, max_length=256)
    pr: GitPullRequest | None = None


class GitPolicy(ManifestModel):
    repos: tuple[GitRepository, ...] = ()
    write: GitWrite | None = None

    @model_validator(mode="after")
    def _unique_repositories(self) -> GitPolicy:
        urls = [repo.url for repo in self.repos]
        if len(set(urls)) != len(urls):
            raise ValueError("git.repos must not repeat a repository url")
        if sum(repo.role == "target" for repo in self.repos) > 1:
            raise ValueError("git.repos names at most one target repository")
        return self

    @property
    def target(self) -> GitRepository | None:
        return next((repo for repo in self.repos if repo.role == "target"), None)


class ProviderEnvironmentStrategy(ManifestModel):
    """How a provider-hosted lane gets its base layer (SPEC-01 §7)."""

    strategy: ProviderEnvironmentStrategyName
    ref: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _ref_by_strategy(self) -> ProviderEnvironmentStrategy:
        if self.strategy == "bind" and self.ref is None:
            raise ValueError("provider_environment strategy bind needs ref")
        if self.strategy != "bind" and self.ref is not None:
            raise ValueError(
                f"provider_environment strategy {self.strategy} names its own environment; "
                "ref is for bind only"
            )
        return self


class DeclaredEnvironment(Protocol):
    """Anything carrying the six additions: an effective ``EnvironmentV2`` or the committed
    ``EnvironmentSelections`` of a definition node. ``model_fields_set`` tells an explicit
    ``null`` (which unsets an inherited field) from an absent one."""

    @property
    def model_fields_set(self) -> set[str]: ...
    @property
    def kit(self) -> KitSelection | None: ...
    @property
    def variables(self) -> tuple[EnvironmentVariable, ...] | None: ...
    @property
    def secrets(self) -> tuple[EnvironmentSecret, ...] | None: ...
    @property
    def network(self) -> NetworkPolicy | None: ...
    @property
    def git(self) -> GitPolicy | None: ...
    @property
    def provider_environment(self) -> ProviderEnvironmentStrategy | None: ...


class EnvironmentAdditions(ManifestModel):
    """The six ``mission/v2`` environment additions, mixed into ``EnvironmentV2``."""

    kit: KitSelection | None = None
    variables: tuple[EnvironmentVariable, ...] | None = None
    secrets: tuple[EnvironmentSecret, ...] | None = None
    network: NetworkPolicy | None = None
    git: GitPolicy | None = None
    provider_environment: ProviderEnvironmentStrategy | None = None

    @model_validator(mode="after")
    def _unique_names(self) -> EnvironmentAdditions:
        for name in ("variables", "secrets"):
            names = [item.name for item in getattr(self, name) or ()]
            if len(set(names)) != len(names):
                raise ValueError(f"{name} must not repeat a name")
        return self


# --- Kit requirements ----------------------------------------------------------------------


class KitSecretRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: EnvironmentName
    optional: bool = False


class KitRequirements(BaseModel):
    """What an Environment Kit's ``requires`` block asks of the manifest that pins it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variables: tuple[EnvironmentName, ...] = ()
    secrets: tuple[KitSecretRequirement, ...] = ()
    egress: tuple[EgressHost, ...] = ()
    git_dependencies: tuple[RepositoryUrl, ...] = ()

    @classmethod
    def from_requires(cls, requires: Mapping[str, Any]) -> KitRequirements:
        """Parse a kit manifest ``requires`` block; a trailing ``?`` marks an optional secret."""

        return cls(
            variables=tuple(requires.get("variables", ())),
            secrets=tuple(
                KitSecretRequirement(name=name.removesuffix("?"), optional=name.endswith("?"))
                for name in requires.get("secrets", ())
            ),
            egress=tuple(requires.get("egress", ())),
            git_dependencies=tuple(requires.get("git_dependencies", ())),
        )


def kit_requirement_issues(
    environment: DeclaredEnvironment,
    kit: KitRequirements,
    pointers: Mapping[str, str],
) -> list[ManifestIssue]:
    """The kit's ``requires`` against what the effective environment declares.

    ``pointers`` maps each addition field (``variables``, ``secrets``, ``network``, ``git``,
    ``kit``) to the environment pointer that set it, so every issue names the manifest
    location an author would edit.
    """

    pin = environment.kit.pin if environment.kit is not None else "the environment kit"
    issues: list[ManifestIssue] = []
    declared_variables = {item.name for item in environment.variables or ()}
    for name in kit.variables:
        if name not in declared_variables:
            issues.append(
                _kit_issue(
                    f"{pointers['variables']}/variables",
                    f"environment kit {pin} requires variable {name}",
                )
            )
    declared_secrets = {item.name for item in environment.secrets or ()}
    for secret in kit.secrets:
        if not secret.optional and secret.name not in declared_secrets:
            issues.append(
                _kit_issue(
                    f"{pointers['secrets']}/secrets",
                    f"environment kit {pin} requires secret {secret.name}",
                )
            )
    network = environment.network
    if network is not None and kit.egress:
        if network.mode == "none":
            issues.append(
                _kit_issue(
                    f"{pointers['network']}/network/mode",
                    f"environment kit {pin} requires egress to {', '.join(kit.egress)}; "
                    "network mode none forbids it",
                )
            )
        elif not network.include_kit:
            for host in kit.egress:
                if not network.allows(host):
                    issues.append(
                        _kit_issue(
                            f"{pointers['network']}/network/allow",
                            f"environment kit {pin} requires egress to {host}; allow it or "
                            "set include_kit",
                        )
                    )
    git = environment.git
    declared_repositories = {repo.url for repo in (git.repos if git is not None else ())}
    for url in kit.git_dependencies:
        if url not in declared_repositories:
            issues.append(
                _kit_issue(
                    f"{pointers['git']}/git/repos",
                    f"environment kit {pin} requires git dependency {url}",
                )
            )
    return issues


def _kit_issue(pointer: str, message: str) -> ManifestIssue:
    return _issue(pointer, message, "kit_requirement_unmet")


# --- Lane rules --------------------------------------------------------------------------------


def environment_lane_issues(
    environment: DeclaredEnvironment,
    lane: LaneProfile | None,
    env_pointer: str,
    *,
    setup_pin: str | None,
    workspace_repo_url: str | None,
) -> list[ManifestIssue]:
    """Lane- and cross-field rules of the additions on one effective environment.

    Deep Agents materializes finite network hosts as worker-tool operation grants, while its
    executable sandbox remains unchanged. Other additions retain compile admission warnings,
    not structural rules, so a mission-wide kit can still carry a Deep Agents node."""

    if lane is None or lane is LaneProfile.DEEP_AGENTS:
        return []
    issues = _combination_issues(environment, env_pointer)
    provider_environment = environment.provider_environment
    if provider_environment is not None:
        offered = PROVIDER_ENVIRONMENT_STRATEGIES.get(lane, frozenset())
        if provider_environment.strategy not in offered:
            issues.append(
                _issue(
                    f"{env_pointer}/provider_environment/strategy",
                    f"lane {lane.value} offers no provider environment strategy "
                    f"{provider_environment.strategy}"
                    + (f" (offers {', '.join(sorted(offered))})" if offered else ""),
                    "strategy_unsupported",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
        elif provider_environment.strategy != "bind" and environment.kit is None:
            issues.append(
                _issue(
                    f"{env_pointer}/provider_environment/strategy",
                    f"strategy {provider_environment.strategy} renders the base layer from an "
                    "environment kit; declare kit",
                    "missing_field",
                )
            )
    if environment.kit is not None and setup_pin is not None and setup_pin != environment.kit.pin:
        issues.append(
            _issue(
                f"{env_pointer}/kit/pin",
                f"kit {environment.kit.pin} differs from execution_environment.setup.pin "
                f"{setup_pin}; the kit is the setup pin",
                "setup_pin_mismatch",
            )
        )
    git = environment.git
    target = git.target if git is not None else None
    if (
        git is not None
        and target is not None
        and workspace_repo_url is not None
        and target.url != workspace_repo_url
    ):
        issues.append(
            _issue(
                f"{env_pointer}/git/repos/{git.repos.index(target)}/url",
                f"the git target {target.url} is not the workspace repository {workspace_repo_url}",
                "repository_mismatch",
            )
        )
    if (
        git is not None
        and git.write is not None
        and git.write.mode != "none"
        and target is None
        and workspace_repo_url is None
    ):
        issues.append(
            _issue(
                f"{env_pointer}/git/write/mode",
                f"git.write {git.write.mode} needs a target repository (git.repos or "
                "workspace.repo)",
                "missing_field",
            )
        )
    if (
        lane is LaneProfile.CLAUDE_CLOUD
        and git is not None
        and environment.network is not None
        and environment.network.include_signal_ingress
    ):
        # Multi-repo Claude cloud sessions load no repo settings or hooks, so callbacks
        # would never be installed (SPEC-01 §6); dependencies come through the mission layer.
        issues.extend(
            _issue(
                f"{env_pointer}/git/repos/{index}",
                "a claude_cloud mission with callbacks cannot add a dependency repository; "
                "clone it in the mission layer",
                "unsupported_combination",
                ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
            )
            for index, repo in enumerate(git.repos)
            if repo.role == "dependency"
        )
    return issues


def _combination_issues(environment: DeclaredEnvironment, env_pointer: str) -> list[ManifestIssue]:
    """Cross-field rules that hold on the merged (effective) environment."""

    issues: list[ManifestIssue] = []
    network = environment.network
    if network is not None and network.allow and network.mode != "allowlist":
        issues.append(
            _issue(
                f"{env_pointer}/network/allow",
                f"network.allow needs mode allowlist, not {network.mode}",
                "invalid_combination",
            )
        )
    if network is not None and network.mode == "none" and network.include_signal_ingress:
        issues.append(
            _issue(
                f"{env_pointer}/network/include_signal_ingress",
                "network mode none cannot include the signal ingress host",
                "invalid_combination",
            )
        )
    write = environment.git.write if environment.git is not None else None
    if write is not None and write.pr is not None and write.mode != "branch_and_pr":
        issues.append(
            _issue(
                f"{env_pointer}/git/write/pr",
                f"git.write.pr needs mode branch_and_pr, not {write.mode}",
                "invalid_combination",
            )
        )
    secrets = {item.name for item in environment.secrets or ()}
    issues.extend(
        _issue(
            f"{env_pointer}/variables/{index}/name",
            f"{variable.name} is declared both as a variable and a secret",
            "name_collision",
        )
        for index, variable in enumerate(environment.variables or ())
        if variable.name in secrets
    )
    return issues


# --- Inheritance -----------------------------------------------------------------------------


def environment_narrowing_issues(
    parent: DeclaredEnvironment,
    child: DeclaredEnvironment,
    overlay: DeclaredEnvironment,
    pointer: str,
) -> list[ManifestIssue]:
    """A child narrows network and secrets and never relaxes git.write (SPEC-01 §3). Unsetting
    an inherited network or write policy with an explicit ``null`` would fall back to the
    deployment's, so it widens too. A kit switch needs the kits' egress, so compile admission
    checks it (:func:`kit_switch_issues`)."""

    return [
        *_network_issues(parent.network, child.network, overlay, pointer),
        *_secret_issues(parent.secrets or (), overlay.secrets, pointer),
        *_git_write_issues(parent.git, child.git, overlay, pointer),
    ]


def _widens(pointer: str, message: str) -> ManifestIssue:
    return _issue(pointer, message, "widens_authority")


def _network_issues(
    parent: NetworkPolicy | None,
    child: NetworkPolicy | None,
    overlay: DeclaredEnvironment,
    pointer: str,
) -> list[ManifestIssue]:
    if parent is None:
        return []
    base = f"{pointer}/network"
    if overlay.network is None and "network" in overlay.model_fields_set:
        return [_widens(base, "network cannot be unset below an inherited policy")]
    if child is None or overlay.network is None:
        return []
    issues: list[ManifestIssue] = []
    if NETWORK_MODE_RANK[child.mode] > NETWORK_MODE_RANK[parent.mode]:
        issues.append(
            _widens(f"{base}/mode", f"network mode {child.mode} widens the inherited {parent.mode}")
        )
    elif child.mode == "allowlist" and "allow" in overlay.network.model_fields_set:
        issues.extend(
            _widens(f"{base}/allow/{index}", f"egress to {host} is not allowed by the parent")
            for index, host in enumerate(child.allow)
            if not parent.allows(host)
        )
    if parent.mode == child.mode == "allowlist":
        for flag in ("include_kit", "include_signal_ingress"):
            if getattr(child, flag) and not getattr(parent, flag):
                issues.append(
                    _widens(f"{base}/{flag}", f"network.{flag} widens the inherited policy")
                )
    return issues


def kit_switch_issues(
    parent: DeclaredEnvironment,
    child: DeclaredEnvironment,
    *,
    parent_kit_egress: Sequence[str],
    child_kit_egress: Sequence[str],
    pointer: str,
) -> list[ManifestIssue]:
    """A child allowlist that includes another kit's egress may bring only hosts the inherited
    policy already allows: its own entries, or its kit's egress when it includes that kit.
    ``pointer`` is the child's ``.../kit/pin``; both kits' egress arrive resolved."""

    inherited, effective = parent.network, child.network
    if (
        child.kit is None
        or child.kit == parent.kit
        or inherited is None
        or effective is None
        or not (inherited.mode == effective.mode == "allowlist")
        or not effective.include_kit
    ):
        return []
    granted = parent_kit_egress if inherited.include_kit and parent.kit is not None else ()
    added = [
        host
        for host in child_kit_egress
        if not inherited.allows(host) and not any(host_covers(entry, host) for entry in granted)
    ]
    if not added:
        return []
    return [
        _widens(
            pointer,
            f"kit {child.kit.pin} adds egress to {', '.join(added)} under network.include_kit; "
            "the inherited policy does not allow it",
        )
    ]


def _secret_issues(
    granted: Sequence[EnvironmentSecret],
    requested: Sequence[EnvironmentSecret] | None,
    pointer: str,
) -> list[ManifestIssue]:
    if requested is None:
        return []
    by_name = {item.name: item for item in granted}
    issues: list[ManifestIssue] = []
    for index, secret in enumerate(requested):
        grant = by_name.get(secret.name)
        if grant is None or grant.ref != secret.ref:
            issues.append(
                _widens(
                    f"{pointer}/secrets/{index}",
                    f"secret {secret.name} ({secret.ref}) is not granted by the parent",
                )
            )
        elif not set(secret.phases) <= set(grant.phases):
            issues.append(
                _widens(
                    f"{pointer}/secrets/{index}/phases",
                    f"secret {secret.name} phases {', '.join(secret.phases)} widen the "
                    f"inherited {', '.join(grant.phases)}",
                )
            )
    return issues


def _git_write_issues(
    parent: GitPolicy | None,
    child: GitPolicy | None,
    overlay: DeclaredEnvironment,
    pointer: str,
) -> list[ManifestIssue]:
    inherited = parent.write if parent is not None else None
    requested = child.write if child is not None else None
    if inherited is None:
        return []
    if overlay.git is None and "git" in overlay.model_fields_set:
        return [_widens(f"{pointer}/git", "git cannot be unset below an inherited write policy")]
    if overlay.git is None or "write" not in overlay.git.model_fields_set:
        return []
    base = f"{pointer}/git/write"
    if requested is None:
        return [_widens(base, "git.write cannot be unset below an inherited write policy")]
    issues: list[ManifestIssue] = []
    if GIT_WRITE_RANK[requested.mode] > GIT_WRITE_RANK[inherited.mode]:
        issues.append(
            _widens(
                f"{base}/mode", f"git.write {requested.mode} relaxes the inherited {inherited.mode}"
            )
        )
    if inherited.pr is not None and requested.pr is not None:
        if inherited.pr.draft and not requested.pr.draft:
            issues.append(
                _widens(f"{base}/pr/draft", "a draft pull request cannot become a ready one")
            )
        if inherited.pr.mode == "mission_control" and requested.pr.mode == "provider":
            issues.append(
                _widens(
                    f"{base}/pr/mode",
                    "a governed pull request cannot be handed to the provider",
                )
            )
    return issues


# --- Binding projection ------------------------------------------------------------------------


def binding_fields(environment: DeclaredEnvironment) -> dict[str, object]:
    """What ``mc.environment_binding.v1`` takes from the manifest alone: ``setup_pin`` (the kit)
    and ``secret_refs`` (``NAME=ref[;phase,...]``, never values). The network policy needs the
    kit's egress and the installation's hosts, so the launch resolves it
    (``domain.execution.network_policy``). Fields the manifest does not declare are left to the
    deployment binding."""

    fields: dict[str, object] = {}
    if environment.kit is not None:
        fields["setup_pin"] = environment.kit.pin
    if environment.secrets is not None:
        fields["secret_refs"] = tuple(item.binding_ref for item in environment.secrets)
    return fields


def secret_names(environment: DeclaredEnvironment) -> tuple[str, ...]:
    return tuple(item.name for item in environment.secrets or ())


def is_secret_like_config_key(key: str) -> bool:
    """Whether a configuration key names a credential (``SECRET_LIKE_CONFIG_KEY_PATTERN``)."""

    return re.search(SECRET_LIKE_CONFIG_KEY_PATTERN, key) is not None


def config_keys(environments: Iterable[DeclaredEnvironment]) -> tuple[str, ...]:
    keys = (
        item.config_key
        for environment in environments
        for item in environment.variables or ()
        if item.config_key is not None
    )
    return tuple(dict.fromkeys(keys))


def host_covers(entry: str, host: str) -> bool:
    """An exact entry covers itself; ``*.example.org`` covers every name below it."""

    return host.endswith(entry[1:]) if entry.startswith("*.") else entry == host


__all__ = [
    "BINDING_SECRET_REF_PATTERN",
    "CONFIG_KEY_PATTERN",
    "CONFIG_REF_PATTERN",
    "ENVIRONMENT_ADDITIONS",
    "MINTED_CREDENTIALS",
    "PROVIDER_ENVIRONMENT_STRATEGIES",
    "SECRET_LIKE_CONFIG_KEY_PATTERN",
    "SECRET_REF_PATTERN",
    "DeclaredEnvironment",
    "EgressHost",
    "EnvironmentAdditions",
    "EnvironmentSecret",
    "EnvironmentVariable",
    "GitPolicy",
    "GitPullRequest",
    "GitRepository",
    "GitWrite",
    "KitRequirements",
    "KitSecretRequirement",
    "KitSelection",
    "NetworkMode",
    "NetworkPolicy",
    "ProviderEnvironmentStrategy",
    "binding_fields",
    "config_keys",
    "environment_lane_issues",
    "environment_narrowing_issues",
    "host_covers",
    "is_secret_like_config_key",
    "kit_requirement_issues",
    "kit_switch_issues",
    "secret_names",
]

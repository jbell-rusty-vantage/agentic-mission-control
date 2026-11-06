"""Provider environments of hosted lanes: the committed-file check, `sync` and `bind` (SPEC-01
section 7; MO-13).

A hosted lane's base layer lives in the provider's environment. Three strategies provide it:

- `sync`: Mission Control creates the environment from the Environment Kit through the
  provider's API for the target repositories. Its name is `mc-<kit id>-<digest8>`, where the
  digest covers the rendered configuration (the kit's base layer plus the projected egress
  settings) and the sorted target repositories, so every mission with the same kit, policy and
  repositories shares one environment, and another repository gets its own (the provider
  resolves an environment from the repositories it covers). A create that finds the name
  taken reads the existing environment back instead: a matching configuration is reused with
  no write, a drifted one (edited elsewhere) is replaced, and one that does not cover the
  target repositories is drift. Every write is read back from the provider's version history
  and its digest must equal the rendered one. The binding's
  secret declarations (except per-run `mint:` credentials) resolve through the Secret Broker
  and are written by name; a reused environment receives only the names it lacks, so a second
  mission causes no update (a rotated value reaches the environment when its configuration
  changes or the name is removed);
- `bind`: an existing environment by name (Mission Control reads its configuration digest and
  version, and writes nothing), or the committed file itself;
- `generate`: the owner applies generated content (SPEC-05); nothing is written here.

The **committed file** a provider resolves before any saved environment (Cursor's
`.cursor/environment.json` on the default branch) is checked first. It is `mc_owned` when its
`name` carries this kit's marker `mc:<kit id>@<kit version>` (ADR-0042) and its configuration
digest equals the kit's rendering, `foreign` when it exists otherwise (no marker, another kit's
marker, or the marker over stale or hand-edited content), and `absent` when there is none. A
foreign file is refused unless the strategy binds that file; an mc-owned file is the kit's base
layer and is used as is (a saved environment would be shadowed by it, so none is synced and a
bind by name is refused). Configuration digests are canonical-JSON digests wherever they come
from (a provider's read-back or the committed file), so one configuration has one digest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal, Protocol

from mission_control.application.secrets.broker import ResolvedSecrets, SecretBroker
from mission_control.application.secrets.delivery import (
    ProviderSecretStore,
    SecretUse,
    deliver_to_store,
)
from mission_control.application.secrets.references import declarations
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.mission_environment import ProviderEnvironmentStrategyName
from mission_control.domain.capabilities.bundles import sha256_hex

PROVIDER_ENVIRONMENT_REFUSED: Final = "PROVIDER_ENVIRONMENT_REFUSED"
PROVIDER_ENVIRONMENT_DRIFT: Final = "PROVIDER_ENVIRONMENT_DRIFT"
# The prefix of every environment name Mission Control syncs.
SYNCED_NAME_PREFIX: Final = "mc-"

EnvironmentAction = Literal["created", "updated", "reused", "bound", "repo_file", "generated"]


class ProviderEnvironmentRefused(RuntimeError):
    """The provider environment cannot be used as the strategy asks; `code` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ProviderEnvironmentExists(Exception):
    """A create found the name taken; `environment_id` is the existing environment."""

    def __init__(self, environment_id: str) -> None:
        super().__init__(f"an environment with this name exists ({environment_id})")
        self.environment_id = environment_id


def kit_marker(kit_id: str, kit_version: str) -> str:
    """The marker an mc-owned configuration carries in its `name` (ADR-0042)."""

    return f"mc:{kit_id}@{kit_version}"


def _json_object(config: str | bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(config)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def config_digest(config: str | bytes) -> str | None:
    """The digest of a configuration's JSON content (key order and spacing do not count);
    None when it is not a JSON object."""

    parsed = _json_object(config)
    return None if parsed is None else sha256_digest(parsed)


def repository_key(url: str) -> str:
    """A repository URL compared without case, a trailing slash or a `.git` suffix."""

    return url.strip().rstrip("/").removesuffix(".git").casefold()


def synced_environment_name(kit_id: str, digest: str, repositories: Sequence[str]) -> str:
    """`mc-<kit id>-<digest8>`: one name per kit, rendered configuration and set of target
    repositories (a provider resolves an environment from the repositories it covers, so two
    repositories never share one)."""

    named = sha256_digest(
        {"config": digest, "repositories": sorted({repository_key(url) for url in repositories})}
    )
    return f"{SYNCED_NAME_PREFIX}{kit_id}-{named.removeprefix('sha256:')[:8]}"


# --- the committed file ----------------------------------------------------------------------


class EnvironmentFileState(StrEnum):
    MC_OWNED = "mc_owned"
    FOREIGN = "foreign"
    ABSENT = "absent"


@dataclass(frozen=True)
class EnvironmentFileCheck:
    """The preflight's reading of the committed environment file at one ref."""

    path: str
    state: EnvironmentFileState
    marker: str | None = None
    digest: str | None = None
    reason: str = ""


def environment_file_marker(content: bytes | None) -> str | None:
    """The Mission Control kit marker a committed file's `name` carries, if any."""

    parsed = None if content is None else _json_object(content)
    name = None if parsed is None else parsed.get("name")
    return name if isinstance(name, str) and name.startswith("mc:") else None


def check_environment_file(
    path: str,
    content: bytes | None,
    *,
    expected_marker: str | None,
    expected_digest: str | None = None,
) -> EnvironmentFileCheck:
    """`mc_owned` only when the file's `name` is exactly `expected_marker` (the bound kit's)
    and its configuration digest is `expected_digest` (the kit's rendering); any other
    existing file, a marker for another kit or over other content included, is `foreign`. The
    digest is the canonical configuration digest (of the raw bytes only when it is not JSON)."""

    if content is None:
        return EnvironmentFileCheck(path, EnvironmentFileState.ABSENT, reason=f"no {path}")
    parsed = _json_object(content)
    digest = config_digest(content) or "sha256:" + sha256_hex(content)
    marker = environment_file_marker(content)
    if marker is not None and marker == expected_marker and digest == expected_digest:
        return EnvironmentFileCheck(
            path, EnvironmentFileState.MC_OWNED, marker, digest, f"{path} carries {marker}"
        )
    if marker is not None and marker == expected_marker:
        reason = (
            f"{path} carries {marker} but its configuration ({digest}) is not the kit's "
            f"rendering ({expected_digest or 'none rendered'})"
        )
    elif marker is not None:
        reason = f"{path} marks {marker}, not {expected_marker or 'a kit this mission pins'}"
    elif parsed is None:
        reason = f"{path} is not a JSON object Mission Control can read"
    else:
        reason = f"{path} carries no Mission Control kit marker"
    return EnvironmentFileCheck(path, EnvironmentFileState.FOREIGN, marker, digest, reason)


# --- the provider's environments API ---------------------------------------------------------


@dataclass(frozen=True)
class ProviderEnvironment:
    """One provider environment as read back: its current configuration (verbatim) and the
    version-history entry that made it current."""

    environment_id: str
    name: str
    version_id: str | None
    config: str | None
    source: str | None = None
    # The repositories it covers; None when the provider did not report them.
    repositories: tuple[str, ...] | None = None

    @property
    def config_digest(self) -> str | None:
        return None if self.config is None else config_digest(self.config)


class ProviderEnvironmentApi(Protocol):
    """A provider's environments API (Cursor `/v1/environments`)."""

    async def create(
        self, name: str, config: str, *, repositories: Sequence[str]
    ) -> ProviderEnvironment:
        """Create and read back; :class:`ProviderEnvironmentExists` when the name is taken."""
        ...

    async def read(self, environment_id: str) -> ProviderEnvironment: ...

    async def find(self, name: str) -> ProviderEnvironment | None: ...

    async def replace(self, environment_id: str, config: str) -> ProviderEnvironment:
        """Replace the whole configuration and read it back."""
        ...

    def secrets(self, environment_id: str) -> ProviderSecretStore: ...


@dataclass(frozen=True)
class AppliedEnvironment:
    """What a hosted agent runs in and how that was established (secret-free)."""

    strategy: ProviderEnvironmentStrategyName
    action: EnvironmentAction
    file: EnvironmentFileCheck
    environment: ProviderEnvironment | None = None
    secret_uses: tuple[SecretUse, ...] = ()
    # Names this apply wrote (a reused environment receives only those it lacked).
    secrets_written: tuple[str, ...] = ()
    # Declared names no shared environment holds: per-run `mint:` credentials and optional
    # declarations without a value.
    omitted_secrets: tuple[str, ...] = ()

    def details(self) -> dict[str, str]:
        """The facts a session handle and receipt record (no value, no configuration)."""

        details = {
            "provider_environment": f"{self.strategy}:{self.action}",
            "provider_environment_file": self.file.state.value,
        }
        if self.environment is not None:
            details["provider_environment_id"] = self.environment.environment_id
            details["provider_environment_name"] = self.environment.name
            if self.environment.version_id is not None:
                details["provider_environment_version"] = self.environment.version_id
            if self.environment.config_digest is not None:
                details["provider_environment_digest"] = self.environment.config_digest
        for key, names in (
            ("provider_environment_secrets", [use.name for use in self.secret_uses]),
            ("provider_environment_secrets_written", self.secrets_written),
            ("provider_environment_secrets_omitted", self.omitted_secrets),
        ):
            if names:
                details[key] = ",".join(sorted(names))
        return details


class ProviderEnvironmentService:
    """Apply one strategy against the committed-file check (SPEC-01 section 7)."""

    def __init__(self, api: ProviderEnvironmentApi, *, broker: SecretBroker | None = None) -> None:
        self._api = api
        self._broker = broker

    async def apply(
        self,
        *,
        strategy: ProviderEnvironmentStrategyName,
        file: EnvironmentFileCheck,
        ref: str | None = None,
        kit_id: str | None = None,
        config: str | None = None,
        secret_refs: Sequence[str] = (),
        repositories: Sequence[str] = (),
    ) -> AppliedEnvironment:
        if strategy == "bind" and ref == file.path:
            if file.state == EnvironmentFileState.ABSENT:
                raise ProviderEnvironmentRefused(
                    PROVIDER_ENVIRONMENT_REFUSED, f"bind names {ref}, which is not committed"
                )
            return AppliedEnvironment(strategy, "bound", file)
        if file.state == EnvironmentFileState.FOREIGN:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED,
                f"{file.reason}; it overrides every saved environment, so launch is refused "
                f"unless provider_environment binds {file.path}",
            )
        if file.state == EnvironmentFileState.MC_OWNED:
            if strategy == "bind":
                raise ProviderEnvironmentRefused(
                    PROVIDER_ENVIRONMENT_REFUSED,
                    f"{file.reason} and overrides environment {ref}; bind {file.path} instead",
                )
            return AppliedEnvironment(strategy, "repo_file", file)
        if strategy == "generate":
            return AppliedEnvironment(strategy, "generated", file)
        if strategy == "bind":
            assert ref is not None
            return await self._bind(ref, file)
        if kit_id is None or config is None:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED, "sync renders the environment from a kit"
            )
        return await self._sync(
            kit_id, config, file, secret_refs=secret_refs, repositories=repositories
        )

    async def _bind(self, ref: str, file: EnvironmentFileCheck) -> AppliedEnvironment:
        environment = await self._api.find(ref)
        if environment is None:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED, f"no provider environment is named {ref}"
            )
        return AppliedEnvironment("bind", "bound", file, environment)

    async def _sync(
        self,
        kit_id: str,
        config: str,
        file: EnvironmentFileCheck,
        *,
        secret_refs: Sequence[str],
        repositories: Sequence[str],
    ) -> AppliedEnvironment:
        expected = config_digest(config)
        if expected is None:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED, "the rendered configuration is not a JSON object"
            )
        # Resolve first: a missing required secret refuses before anything reaches the provider.
        resolved, minted = await self._resolve_stored(secret_refs)
        name = synced_environment_name(kit_id, expected, repositories)
        action: EnvironmentAction
        try:
            environment = await self._api.create(name, config, repositories=repositories)
            action = "created"
        except ProviderEnvironmentExists as exists:
            environment = await self._api.read(exists.environment_id)
            _require_coverage(environment, repositories)
            action = "reused"
            if environment.config_digest != expected:
                environment = await self._api.replace(environment.environment_id, config)
                action = "updated"
        if environment.config_digest != expected:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_DRIFT,
                f"environment {name} reads back {environment.config_digest}, not {expected}",
            )
        uses: tuple[SecretUse, ...] = ()
        written: tuple[str, ...] = ()
        if resolved is not None:
            uses, written = await self._write_secrets(
                environment, resolved, every_value=action != "reused"
            )
        return AppliedEnvironment(
            "sync",
            action,
            file,
            environment,
            secret_uses=uses,
            secrets_written=written,
            omitted_secrets=(*(resolved.omitted if resolved else ()), *minted),
        )

    async def _resolve_stored(
        self, secret_refs: Sequence[str]
    ) -> tuple[ResolvedSecrets | None, tuple[str, ...]]:
        """The declared values a shared environment holds, and the per-run `mint:` names that
        never go into one."""

        declared = declarations(secret_refs)
        stored = tuple(item for item in declared if item.ref.scheme != "mint")
        minted = tuple(item.name for item in declared if item.ref.scheme == "mint")
        if not stored:
            return None, minted
        if self._broker is None:
            raise ProviderEnvironmentRefused(
                PROVIDER_ENVIRONMENT_REFUSED,
                f"{', '.join(item.name for item in stored)} need a composed Secret Broker",
            )
        return await self._broker.resolve_declarations(stored), minted

    async def _write_secrets(
        self, environment: ProviderEnvironment, resolved: ResolvedSecrets, *, every_value: bool
    ) -> tuple[tuple[SecretUse, ...], tuple[str, ...]]:
        """Write by name: every value into a created or updated environment, only the names a
        reused one lacks (so a second mission causes no update)."""

        store = self._api.secrets(environment.environment_id)
        values: Mapping[str, str] = resolved.values
        if not every_value:
            present = {name.upper() for name in await store.names()}
            values = {name: value for name, value in values.items() if name.upper() not in present}
        await deliver_to_store(ResolvedSecrets(values=values, held=resolved.held), store)
        uses = (
            *(SecretUse(name, store.channel, store.target) for name in resolved.values),
            *(SecretUse(name, store.channel, store.target, held=True) for name in resolved.held),
        )
        return uses, tuple(values)


def _require_coverage(environment: ProviderEnvironment, repositories: Sequence[str]) -> None:
    """A reused environment must cover every target repository: the provider resolves an
    environment from its repositories, so one that does not cover them would leave the agent
    without the kit's base layer and secrets."""

    if environment.repositories is None:
        return
    covered = {repository_key(url) for url in environment.repositories}
    missing = sorted(url for url in repositories if repository_key(url) not in covered)
    if missing:
        raise ProviderEnvironmentRefused(
            PROVIDER_ENVIRONMENT_DRIFT,
            f"environment {environment.name} does not cover {', '.join(missing)}",
        )


__all__ = [
    "PROVIDER_ENVIRONMENT_DRIFT",
    "PROVIDER_ENVIRONMENT_REFUSED",
    "SYNCED_NAME_PREFIX",
    "AppliedEnvironment",
    "EnvironmentAction",
    "EnvironmentFileCheck",
    "EnvironmentFileState",
    "ProviderEnvironment",
    "ProviderEnvironmentApi",
    "ProviderEnvironmentExists",
    "ProviderEnvironmentRefused",
    "ProviderEnvironmentService",
    "check_environment_file",
    "config_digest",
    "environment_file_marker",
    "kit_marker",
    "repository_key",
    "synced_environment_name",
]

"""The Secret Broker: resolves secret references from installation sources (SPEC-01 section 4).

Sources are installation-configured and never chosen by a mission:

* the worker environment serves `environment:` references (the deployment's own credentials,
  as before the broker);
* the installation's secret store serves `secret:`/`vault:` references: a secret-store file or
  the owner's keyring locally, Supabase Vault when hosted. With no store composed such a
  reference is unavailable; the broker never falls back to the worker environment;
* store paths the installation lists as provider-held are never read: their values already
  live in the provider's store, so they resolve to names that delivery verifies there;
* `mint:` references are minted per run by the `CredentialMinter` for the attempt's binding.

The broker is the deployment's `SecretResolutionPort` (credential references of an operation)
and resolves a binding's declarations for one phase into `ResolvedSecrets`. Every value it
resolves or mints joins the process's `SecretValueRegistry`, so frames, logs and receipts
redact it; the lane that delivers a run's values scans that run's commits for them. Values are
returned to the caller only; a failure names the variable and reference, never a value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol

from mission_control.application.secrets.minting import (
    CredentialBinding,
    LaunchBinding,
    MintedCredential,
    MintedToken,
)
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.application.secrets.references import (
    BrokerRef,
    RefScheme,
    SecretDeclaration,
    SecretPhase,
)
from mission_control.domain.authoring.contracts import SecretRef


class SecretUnavailable(LookupError):
    """A reference names a secret this installation cannot serve."""


class SecretSource(Protocol):
    """One installation source; `None` when it holds no value under `key`."""

    async def read(self, key: str) -> str | None: ...


class SecretMinter(Protocol):
    async def mint(
        self,
        purpose: str,
        binding: CredentialBinding | LaunchBinding,
        *,
        deadline: datetime | None = None,
    ) -> MintedToken: ...


@dataclass(frozen=True)
class ResolvedSecrets:
    """One phase's declarations, resolved. `values` maps variable names to values; `held`
    names the variables whose values live in the provider's store (verified at delivery);
    `minted` records the credentials minted for them; `omitted` names optional variables
    without a value."""

    values: Mapping[str, str] = field(default_factory=dict, repr=False)
    held: tuple[str, ...] = ()
    minted: tuple[MintedCredential, ...] = ()
    omitted: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return (*self.values, *self.held)

    def __repr__(self) -> str:
        return f"ResolvedSecrets(names={self.names!r}, omitted={self.omitted!r})"


# `SecretRef` providers (the operation contract's spelling) and the scheme each one names.
_REF_SCHEMES: Final[dict[str, RefScheme]] = {"environment": "environment", "vault": "store"}


class SecretBroker:
    def __init__(
        self,
        *,
        environment: SecretSource,
        store: SecretSource | None = None,
        provider_held: Iterable[str] = (),
        minter: SecretMinter | None = None,
        registry: SecretValueRegistry | None = None,
    ) -> None:
        self._environment = environment
        self._store = store
        self._held = frozenset(provider_held)
        self._minter = minter
        self.registry = registry or SecretValueRegistry()

    async def resolve(self, refs: tuple[SecretRef, ...]) -> Mapping[str, str]:
        """`SecretResolutionPort`: each reference's value keyed `<provider>:<key>`."""

        resolved: dict[str, str] = {}
        for ref in refs:
            reference = f"{ref.provider}:{ref.key}"
            scheme = _REF_SCHEMES.get(ref.provider)
            if scheme is None:
                raise SecretUnavailable(
                    f"secret provider {ref.provider!r} is not composed in this deployment"
                )
            value = await self._read(BrokerRef(scheme=scheme, key=ref.key))
            if not value:
                raise SecretUnavailable(f"credential reference {reference} has no value")
            resolved[reference] = value
        self.registry.add(resolved.values())
        return resolved

    async def resolve_declarations(
        self,
        declarations: Iterable[SecretDeclaration],
        *,
        phase: SecretPhase | None = None,
        binding: CredentialBinding | None = None,
        deadline: datetime | None = None,
    ) -> ResolvedSecrets:
        """The declarations `phase` receives, resolved; `binding` (and the mission `deadline`)
        bind the credentials `mint:` references issue. A required declaration without a value
        fails the whole resolution."""

        values: dict[str, str] = {}
        held: list[str] = []
        minted: list[MintedCredential] = []
        omitted: list[str] = []
        for declaration in declarations:
            if not declaration.receives(phase):
                continue
            ref = declaration.ref
            if ref.scheme == "mint":
                if self._minter is None or binding is None:
                    raise SecretUnavailable(
                        f"{declaration.name} ({ref}) needs a credential store and a run binding"
                    )
                token = await self._minter.mint(ref.key, binding, deadline=deadline)
                values[declaration.name] = token.value
                minted.append(token.record)
                continue
            if ref.scheme == "store" and ref.key in self._held:
                held.append(declaration.name)
                continue
            value = await self._read(ref)
            if value:
                values[declaration.name] = value
            elif declaration.required:
                raise SecretUnavailable(f"{declaration.name} ({ref}) has no value")
            else:
                omitted.append(declaration.name)
        self.registry.add(values.values())
        return ResolvedSecrets(
            values=values, held=tuple(held), minted=tuple(minted), omitted=tuple(omitted)
        )

    async def _read(self, ref: BrokerRef) -> str | None:
        if ref.scheme == "environment":
            return await self._environment.read(ref.key)
        if ref.key in self._held:
            raise SecretUnavailable(f"{ref} is held by the provider; its value is never read")
        if self._store is None:
            raise SecretUnavailable(f"{ref} names the secret store, which is not composed")
        return await self._store.read(ref.key)


__all__ = ["ResolvedSecrets", "SecretBroker", "SecretSource", "SecretUnavailable"]

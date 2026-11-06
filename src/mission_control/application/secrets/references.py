"""Secret references and declarations the Secret Broker resolves (SPEC-01 sections 3-4; ADR-0043).

A reference names where a value lives, never the value:

* `environment:<NAME>`: the worker process environment (the deployment's own credentials);
* `secret:<path>` (the manifest spelling) or `vault:<path>` (the `SecretRef` spelling): the
  installation's secret store, which is the owner's keyring or a secret-store file outside any
  repository locally, and Supabase Vault when Mission Control is hosted. A path the installation
  lists as provider-held is never read: its value already lives in the provider's store, and
  delivery only verifies the name there;
* `mint:<purpose>`: a per-run credential Mission Control issues (`mint:signal_token`).

A declaration binds one environment variable name to one reference, the phases that receive it
(`setup` for the mission layer, `agent` for the session) and whether it is required. Bindings
carry each declaration as the entry `NAME[?]=<ref>[;phase,...]`: names and references only, so a
compiled program, a binding or a log never holds a value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal, cast

RefScheme = Literal["environment", "store", "mint"]
SecretPhase = Literal["setup", "agent"]

ALL_PHASES: Final[tuple[SecretPhase, ...]] = ("setup", "agent")

# Reference prefixes and the source each one names.
_SCHEMES: Final[dict[str, RefScheme]] = {
    "environment": "environment",
    "secret": "store",
    "vault": "store",
    "mint": "mint",
}
_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,254}")
_KEY: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,189}")


class SecretReferenceError(ValueError):
    """A reference or declaration that is not in the broker's grammar."""


@dataclass(frozen=True)
class BrokerRef:
    """One parsed reference: the source it names and the key inside that source."""

    scheme: RefScheme
    key: str

    @classmethod
    def parse(cls, ref: str) -> BrokerRef:
        prefix, separator, key = ref.partition(":")
        scheme = _SCHEMES.get(prefix)
        if not separator or scheme is None or not _KEY.fullmatch(key):
            raise SecretReferenceError(
                "a secret reference is environment:<NAME>, secret:<path>, vault:<path> or "
                "mint:<purpose>"
            )
        if scheme == "environment" and not _NAME.fullmatch(key):
            raise SecretReferenceError("an environment reference names a variable")
        return cls(scheme=scheme, key=key)

    def __str__(self) -> str:
        prefix = "secret" if self.scheme == "store" else self.scheme
        return f"{prefix}:{self.key}"


@dataclass(frozen=True)
class SecretDeclaration:
    """`name` receives the value `ref` resolves to, in the declared `phases`."""

    name: str
    ref: BrokerRef
    phases: tuple[SecretPhase, ...] = ALL_PHASES
    required: bool = True

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise SecretReferenceError(f"{self.name!r} is not an environment variable name")
        if not self.phases or not set(self.phases) <= set(ALL_PHASES):
            raise SecretReferenceError("a declaration names setup and/or agent phases")

    def receives(self, phase: SecretPhase | None) -> bool:
        return phase is None or phase in self.phases

    @property
    def binding_entry(self) -> str:
        """The declaration as a binding carries it (`NAME[?]=<ref>[;phase,...]`)."""

        marker = "" if self.required else "?"
        phases = "" if self.phases == ALL_PHASES else ";" + ",".join(self.phases)
        return f"{self.name}{marker}={self.ref}{phases}"

    @classmethod
    def parse(cls, entry: str) -> SecretDeclaration:
        target, separator, rest = entry.partition("=")
        if not separator:
            raise SecretReferenceError("a binding secret entry is NAME[?]=<ref>[;phase,...]")
        ref, _, listed = rest.partition(";")
        phases = tuple(item.strip() for item in listed.split(",")) if listed else ALL_PHASES
        if not set(phases) <= set(ALL_PHASES):
            raise SecretReferenceError("a declaration names setup and/or agent phases")
        required = not target.endswith("?")
        return cls(
            name=target.removesuffix("?"),
            ref=BrokerRef.parse(ref),
            phases=cast(tuple[SecretPhase, ...], phases),
            required=required,
        )


def declarations(entries: Iterable[str]) -> tuple[SecretDeclaration, ...]:
    """A binding's secret entries as declarations; a variable is declared at most once."""

    parsed = tuple(SecretDeclaration.parse(entry) for entry in entries)
    names = [item.name.upper() for item in parsed]
    if len(names) != len(set(names)):
        raise SecretReferenceError("a variable is declared more than once")
    return parsed


__all__ = [
    "ALL_PHASES",
    "BrokerRef",
    "RefScheme",
    "SecretDeclaration",
    "SecretPhase",
    "SecretReferenceError",
    "declarations",
]

"""MO-11: the Secret Broker resolves references from installation sources only.

The worker environment serves `environment:` references, the installation store serves
`secret:`/`vault:` references (never the worker environment as a fallback), provider-held paths
are never read, `mint:` references are minted for the attempt's binding, and every resolved
value joins the redaction registry. Declarations parse from and print to the `NAME=<ref>`
entries a binding carries.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from mission_control.adapters.secrets.minted import InMemoryMintedCredentialStore
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker, SecretUnavailable
from mission_control.application.secrets.minting import (
    TOKEN_PATTERN,
    CredentialBinding,
    CredentialMinter,
    token_digest,
)
from mission_control.application.secrets.references import (
    BrokerRef,
    SecretDeclaration,
    SecretReferenceError,
    declarations,
)
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.execution.bindings import EnvironmentBinding

STORE_VALUE = "store-value-for-firecrawl"
WORKER_VALUE = "worker-value-for-tavily"
BINDING = CredentialBinding(request_scope="scope", run_id="run", unit_id="unit", generation=3)


class DictSource:
    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = dict(values)
        self.reads: list[str] = []

    async def read(self, key: str) -> str | None:
        self.reads.append(key)
        return self.values.get(key)


def broker(**changes: object) -> tuple[SecretBroker, DictSource]:
    store = DictSource({"firecrawl/api_key": STORE_VALUE, "held/key": "never-read-value"})
    fields: dict[str, object] = {
        "environment": WorkerEnvironmentSource({"TAVILY_API_KEY": WORKER_VALUE, "EMPTY": ""}),
        "store": store,
        "provider_held": ("cursor/team_key",),
        "minter": CredentialMinter(InMemoryMintedCredentialStore()),
    }
    fields.update(changes)
    return SecretBroker(**fields), store  # type: ignore[arg-type]


def test_the_reference_grammar_and_binding_entries_round_trip() -> None:
    assert BrokerRef.parse("secret:firecrawl/api_key") == BrokerRef("store", "firecrawl/api_key")
    assert BrokerRef.parse("vault:firecrawl/api_key") == BrokerRef("store", "firecrawl/api_key")
    assert BrokerRef.parse("mint:signal_token") == BrokerRef("mint", "signal_token")
    assert str(BrokerRef.parse("environment:TAVILY_API_KEY")) == "environment:TAVILY_API_KEY"
    for bad in ("sk-live-value", "env:NAME", "secret:", "environment:not a name", "mint"):
        with pytest.raises(SecretReferenceError):
            BrokerRef.parse(bad)

    declared = (
        SecretDeclaration("FIRECRAWL_API_KEY", BrokerRef.parse("secret:firecrawl/api_key")),
        SecretDeclaration(
            "MC_SIGNAL_TOKEN", BrokerRef.parse("mint:signal_token"), phases=("agent",)
        ),
        SecretDeclaration("LOG_TOKEN", BrokerRef.parse("vault:log/token"), required=False),
    )
    entries = tuple(item.binding_entry for item in declared)
    assert entries == (
        "FIRECRAWL_API_KEY=secret:firecrawl/api_key",
        "MC_SIGNAL_TOKEN=mint:signal_token;agent",
        "LOG_TOKEN?=secret:log/token",
    )
    assert declarations(entries) == declared
    # A binding carries the entries as its secret references (names and references only).
    EnvironmentBinding(kind="local_workspace", host_profile="worker", secret_refs=entries)
    with pytest.raises(SecretReferenceError, match="more than once"):
        declarations(("A=secret:x", "a=secret:y"))
    with pytest.raises(SecretReferenceError, match="phases"):
        SecretDeclaration.parse("A=secret:x;build")


async def test_the_port_resolves_environment_and_store_references_only() -> None:
    secrets, _store = broker()
    resolved = await secrets.resolve(
        (
            SecretRef(provider="environment", key="TAVILY_API_KEY"),
            SecretRef(provider="vault", key="firecrawl/api_key"),
        )
    )
    assert resolved == {
        "environment:TAVILY_API_KEY": WORKER_VALUE,
        "vault:firecrawl/api_key": STORE_VALUE,
    }
    assert set(secrets.registry.values()) == {WORKER_VALUE, STORE_VALUE}
    with pytest.raises(SecretUnavailable, match="not composed"):
        await secrets.resolve((SecretRef(provider="aws-secrets-manager", key="x"),))
    with pytest.raises(SecretUnavailable, match="no value"):
        await secrets.resolve((SecretRef(provider="environment", key="EMPTY"),))


async def test_without_a_store_a_store_reference_never_falls_back_to_the_worker() -> None:
    secrets, _store = broker(
        store=None, environment=WorkerEnvironmentSource({"FIRECRAWL_API_KEY": "worker-copy"})
    )
    with pytest.raises(SecretUnavailable, match="not composed"):
        await secrets.resolve((SecretRef(provider="vault", key="FIRECRAWL_API_KEY"),))


async def test_declarations_resolve_per_phase_with_held_minted_and_optional_names() -> None:
    secrets, store = broker()
    entries = (
        "FIRECRAWL_API_KEY=secret:firecrawl/api_key",
        "TAVILY_API_KEY=environment:TAVILY_API_KEY;setup",
        "CURSOR_TEAM_KEY=secret:cursor/team_key",
        "MC_SIGNAL_TOKEN=mint:signal_token;agent",
        "OPTIONAL_KEY?=secret:missing/key",
    )
    resolved = await secrets.resolve_declarations(
        declarations(entries), phase="agent", binding=BINDING
    )

    assert set(resolved.values) == {"FIRECRAWL_API_KEY", "MC_SIGNAL_TOKEN"}
    assert resolved.values["FIRECRAWL_API_KEY"] == STORE_VALUE
    token = resolved.values["MC_SIGNAL_TOKEN"]
    assert TOKEN_PATTERN.fullmatch(token)
    (minted,) = resolved.minted
    assert minted.binding == BINDING and minted.digest == token_digest(token)
    assert resolved.held == ("CURSOR_TEAM_KEY",) and resolved.omitted == ("OPTIONAL_KEY",)
    assert "cursor/team_key" not in store.reads, "a provider-held value is never read"
    assert STORE_VALUE not in repr(resolved) and token not in repr(resolved)
    assert {STORE_VALUE, token} <= set(secrets.registry.values())


async def test_a_required_secret_without_a_value_fails_the_resolution() -> None:
    secrets, _store = broker()
    with pytest.raises(SecretUnavailable, match=r"MISSING_KEY \(secret:missing/key\)"):
        await secrets.resolve_declarations(declarations(("MISSING_KEY=secret:missing/key",)))
    with pytest.raises(SecretUnavailable, match="held by the provider"):
        await secrets.resolve((SecretRef(provider="vault", key="cursor/team_key"),))


async def test_minting_needs_a_credential_store_and_a_run_binding() -> None:
    entry = declarations(("MC_SIGNAL_TOKEN=mint:signal_token",))
    secrets, _store = broker(minter=None)
    with pytest.raises(SecretUnavailable, match="credential store"):
        await secrets.resolve_declarations(entry, binding=BINDING)
    secrets, _store = broker()
    with pytest.raises(SecretUnavailable, match="run binding"):
        await secrets.resolve_declarations(entry)

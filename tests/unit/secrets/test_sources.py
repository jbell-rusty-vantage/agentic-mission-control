"""MO-11: the installation sources the Secret Broker reads (file, keyring, worker env).

Supabase Vault is proven against real PostgreSQL in
`tests/integration/postgres/test_secret_broker_vault_source.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from keyring.errors import NoKeyringError

from mission_control.adapters.secrets.sources import (
    KeyringSecretSource,
    SecretStoreFile,
    WorkerEnvironmentSource,
)
from mission_control.application.secrets.broker import SecretUnavailable


async def test_the_secret_store_file_lives_outside_every_repository(tmp_path: Path) -> None:
    store = tmp_path / "owner" / "secrets.json"
    store.parent.mkdir()
    store.write_text(json.dumps({"firecrawl/api_key": "fc-store-value"}), encoding="utf-8")
    source = SecretStoreFile(store)
    assert await source.read("firecrawl/api_key") == "fc-store-value"
    assert await source.read("absent/key") is None
    # An owner's edit applies to the next resolution.
    store.write_text(json.dumps({"firecrawl/api_key": "fc-rotated"}), encoding="utf-8")
    assert await source.read("firecrawl/api_key") == "fc-rotated"

    repository = tmp_path / "repo"
    (repository / ".git").mkdir(parents=True)
    (repository / "config").mkdir()
    with pytest.raises(ValueError, match="outside every git repository"):
        SecretStoreFile(repository / "config" / "secrets.json")


async def test_an_unreadable_store_file_is_unavailable_without_its_content(
    tmp_path: Path,
) -> None:
    missing = SecretStoreFile(tmp_path / "missing.json")
    with pytest.raises(SecretUnavailable, match="does not exist"):
        await missing.read("key")
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"key": ["leaked-looking-value"]}', encoding="utf-8")
    with pytest.raises(SecretUnavailable) as refused:
        await SecretStoreFile(malformed).read("key")
    assert "leaked-looking-value" not in str(refused.value)


class FakeKeyring:
    def __init__(self, entries: dict[tuple[str, str], str] | None = None) -> None:
        self.entries = entries or {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.entries.get((service_name, username))


class NoBackend:
    def get_password(self, service_name: str, username: str) -> str | None:
        raise NoKeyringError("no recommended backend")


async def test_the_keyring_reads_entries_under_the_service_name() -> None:
    source = KeyringSecretSource(
        "mission-control", FakeKeyring({("mission-control", "firecrawl/api_key"): "fc-key"})
    )
    assert await source.read("firecrawl/api_key") == "fc-key"
    assert await source.read("other/key") is None
    with pytest.raises(SecretUnavailable, match="keyring is not available"):
        await KeyringSecretSource("mission-control", NoBackend()).read("firecrawl/api_key")


async def test_the_worker_environment_reports_empty_values_as_absent() -> None:
    source = WorkerEnvironmentSource({"TAVILY_API_KEY": "tvly-value", "EMPTY": ""})
    assert await source.read("TAVILY_API_KEY") == "tvly-value"
    assert await source.read("EMPTY") is None and await source.read("ABSENT") is None

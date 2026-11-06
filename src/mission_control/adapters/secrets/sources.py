"""Installation sources the Secret Broker reads (SPEC-01 section 4; ADR-0043).

* `WorkerEnvironmentSource`: the worker process environment (`environment:` references).
* `SecretStoreFile`: a JSON object of `{"<path>": "<value>"}` in a file outside every git
  working tree (the local default store). It is re-read on each lookup, so an owner's edit
  applies to the next resolution; a file inside a repository is refused at composition.
* `KeyringSecretSource`: the owner's OS keyring, one entry per path under a service name.
* `SupabaseVaultSource`: Supabase Vault (hosted Mission Control), read by secret name from
  `vault.decrypted_secrets` over a dedicated connection pool whose role may read that view.

Each returns `None` for a path it does not hold and never logs a value.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import asyncpg
import keyring
from keyring.errors import KeyringError

from mission_control.application.secrets.broker import SecretUnavailable


class WorkerEnvironmentSource:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ

    async def read(self, key: str) -> str | None:
        return self._environ.get(key) or None


def _inside_git_worktree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.parents)


class SecretStoreFile:
    def __init__(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if _inside_git_worktree(resolved):
            raise ValueError("the secret store file must live outside every git repository")
        self._path = resolved

    async def read(self, key: str) -> str | None:
        return (await asyncio.to_thread(self._load)).get(key) or None

    def _load(self) -> dict[str, str]:
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SecretUnavailable("the secret store file does not exist") from None
        except (OSError, ValueError):
            raise SecretUnavailable("the secret store file is unreadable") from None
        if not isinstance(document, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in document.items()
        ):
            raise SecretUnavailable('the secret store file is a JSON object of "path": "value"')
        return document


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...


class KeyringSecretSource:
    def __init__(self, service: str, backend: KeyringBackend | None = None) -> None:
        self._service = service
        self._backend: KeyringBackend = backend if backend is not None else keyring.get_keyring()

    async def read(self, key: str) -> str | None:
        try:
            value = await asyncio.to_thread(self._backend.get_password, self._service, key)
        except KeyringError:
            raise SecretUnavailable("the owner keyring is not available on this worker") from None
        return value or None


VAULT_READ_SQL = "SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name = $1"


class SupabaseVaultSource:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def read(self, key: str) -> str | None:
        try:
            async with self._pool.acquire() as connection:
                value = await connection.fetchval(VAULT_READ_SQL, key)
        except asyncpg.PostgresError as error:
            raise SecretUnavailable(
                f"Supabase Vault refused the read ({type(error).__name__})"
            ) from None
        return str(value) if value else None


__all__ = [
    "VAULT_READ_SQL",
    "KeyringBackend",
    "KeyringSecretSource",
    "SecretStoreFile",
    "SupabaseVaultSource",
    "WorkerEnvironmentSource",
]

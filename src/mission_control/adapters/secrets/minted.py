"""A process-local `MintedCredentialStore` (digests only).

It serves one process that both mints and verifies (a single-process local installation and
the tests). A credential that another process verifies, such as a signal token checked at the
ingress, needs the shared PostgreSQL store over `ingress_credential`
(`adapters/postgres/ingress.py`, migration 0035).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime

from mission_control.application.secrets.minting import CredentialBinding, MintedCredential


class InMemoryMintedCredentialStore:
    def __init__(self) -> None:
        self._records: dict[str, MintedCredential] = {}
        self._lock = asyncio.Lock()

    async def insert(self, record: MintedCredential) -> None:
        async with self._lock:
            if record.digest in self._records:
                raise ValueError("a credential with this digest is already stored")
            self._records[record.digest] = record

    async def by_digest(self, digest: str) -> MintedCredential | None:
        return self._records.get(digest)

    async def revoke(
        self,
        request_scope: str,
        run_id: str,
        *,
        at: datetime,
        unit_id: str | None = None,
        below_generation: int | None = None,
    ) -> int:
        async with self._lock:
            revoked = 0
            for digest, record in self._records.items():
                binding = record.binding
                if (
                    record.revoked_at is None
                    and isinstance(binding, CredentialBinding)
                    and binding.request_scope == request_scope
                    and binding.run_id == run_id
                    and (unit_id is None or binding.unit_id == unit_id)
                    and (below_generation is None or binding.generation < below_generation)
                ):
                    self._records[digest] = replace(record, revoked_at=at)
                    revoked += 1
            return revoked


__all__ = ["InMemoryMintedCredentialStore"]

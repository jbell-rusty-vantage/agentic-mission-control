"""Scoped custody read of a sealed async child contract (OVE-184).

The governed spawn writes the parent's ``AsyncSubagentContract`` (its ``child_binding``
included) to ``mission_control.subordinate_contract`` before any provider call. The Agent
Server's sealed-child graph reads it back here under the caller's verified request scope:
forced row-level security makes another scope's contract invisible, and the contract and
binding validators recompute both digests on load. The table is immutable, so what the server
materializes is exactly what the parent sealed.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.run_control.canonical import SCOPE
from mission_control.domain.execution.contracts import AsyncSubagentContract


class PostgresSealedChildCustody:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def contract(
        self, request_scope: str, contract_digest: str
    ) -> AsyncSubagentContract | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, request_scope)
            rows = await connection.fetch(
                "SELECT payload FROM mission_control.subordinate_contract "
                f"WHERE {SCOPE} AND contract_digest = $4",
                *args,
                contract_digest,
            )
        if len(rows) != 1:
            return None
        payload: Any = rows[0]["payload"]
        contract = AsyncSubagentContract.model_validate(
            json.loads(payload) if isinstance(payload, str) else dict(payload)
        )
        return contract if contract.contract_digest == contract_digest else None


__all__ = ["PostgresSealedChildCustody"]

"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_signal_ingress_postgres.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest_asyncio

from mission_control.adapters.postgres.ingress import (
    PostgresIngressStore,
    PostgresMintedCredentialStore,
    PostgresSessionBindings,
)
from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.secrets.minting import CredentialBinding, CredentialMinter
from mission_control.application.signals.contracts import IngressRejected
from mission_control.application.signals.ports import OidcIdentity
from mission_control.application.signals.service import IngressKeys, SignalIngressService
from tests.support.db import CommonDatabase, ingress_login
from tests.support.db_builders import admit_unit_attempt
from tests.support.provider_webhooks import ANTHROPIC_TEST_SECRET, OPENAI_TEST_SECRET

ENV_MASTER = b"environment-key-master-for-disposable-tests"
CURSOR_MASTER = b"cursor-webhook-master-for-disposable-tests"
GITHUB_SECRET = "github-webhook-secret"
HARNESS_EXECUTION = "0192a4f0-0000-7000-8000-0000000000e1"
GATE_CONTEXT = {
    "harness_execution_id": HARNESS_EXECUTION,
    "lane_profile": "cursor_cloud",
    "disallowed_tools": ["WebFetch"],
}


class FakeOidc:
    """Stands in for `CursorOidcVerifier` (proved on its own against signed JWTs)."""

    async def verify(self, token: str) -> OidcIdentity:
        if not token.startswith("oidc:"):
            raise IngressRejected(401, "invalid_token")
        return OidcIdentity(provider="cursor", session_id=token.removeprefix("oidc:"))


class FakeUploads:
    async def signed_upload(self, storage_key: str) -> SignedUpload:
        return SignedUpload(path=storage_key, url=f"https://storage.test/{storage_key}", token="t")


@dataclass
class Ingress:
    db: CommonDatabase
    runtime: asyncpg.Pool
    edge: asyncpg.Pool
    scope: str
    run_key: str
    unit_key: str
    minter: CredentialMinter
    sessions: PostgresSessionBindings
    store: PostgresIngressStore
    service: SignalIngressService

    @property
    def binding(self) -> CredentialBinding:
        return CredentialBinding(self.scope, self.run_key, self.unit_key, 1)

    async def owner(self, query: str, *args: Any) -> list[asyncpg.Record]:
        connection = await asyncpg.connect(self.db.owner_dsn)
        try:
            return list(await connection.fetch(query, *args))
        finally:
            await connection.close()

    async def inbox(self, kind: str | None = None) -> list[asyncpg.Record]:
        return await self.owner(
            "SELECT * FROM mission_control.ingress_inbox "
            "WHERE $1::text IS NULL OR kind = $1 ORDER BY received_at, ingress_id",
            kind,
        )


@pytest_asyncio.fixture
async def ingress(common_db: CommonDatabase) -> AsyncIterator[Ingress]:
    runtime = await common_db.pool("mission_control_runtime")
    edge = await asyncpg.create_pool(
        await ingress_login(common_db), min_size=1, max_size=4, statement_cache_size=0
    )
    try:
        admitted = await admit_unit_attempt(runtime, common_db)
        scope = common_db.scope()
        store = PostgresIngressStore(
            edge, installation_id=common_db.installation_id, application_id="biotech"
        )
        service = SignalIngressService(
            store,
            keys=IngressKeys(
                environment_key_master=ENV_MASTER,
                cursor_webhook_master=CURSOR_MASTER,
                webhook_secrets={
                    "anthropic": ANTHROPIC_TEST_SECRET,
                    "openai": OPENAI_TEST_SECRET,
                    "github": GITHUB_SECRET,
                },
            ),
            oidc=FakeOidc(),
            uploads=FakeUploads(),
        )
        yield Ingress(
            db=common_db,
            runtime=runtime,
            edge=edge,
            scope=scope,
            run_key=admitted.run_key,
            unit_key=admitted.unit.unit_key,
            minter=CredentialMinter(PostgresMintedCredentialStore(runtime, scope)),
            sessions=PostgresSessionBindings(runtime),
            store=store,
            service=service,
        )
    finally:
        await edge.close()
        await runtime.close()


def bearer(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def signal(signal_id: str, kind: str = "milestone", **data: Any) -> dict[str, Any]:
    return {"signal_id": signal_id, "type": kind, "seq": 1, "data": data}


def batch(*signals: dict[str, Any]) -> bytes:
    return json.dumps({"signals": list(signals)}).encode()


def gate_body(signal_id: str, effect_ref: str, tool: str = "Shell", **extra: Any) -> bytes:
    return json.dumps(
        {
            "signal_id": signal_id,
            "hook_event": "before_shell",
            "effect_ref": effect_ref,
            "effect_kind": "shell",
            "tool": tool,
            "tool_input": {"command": "pytest -q"},
            **extra,
        }
    ).encode()

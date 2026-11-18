"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_mission_socket_postgres.py.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

import mission_control.bootstrap.api as api_module
from mission_control.adapters.auth.jwt import ActorGrant, ApplicationAuthentication
from mission_control.adapters.realtime.stream_source import PostgresStreamSource
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.streams.pump import PumpSettings
from mission_control.application.streams.service import MissionStreamService
from mission_control.bootstrap.api import ApplicationDeployment, MissionDeployment
from mission_control.domain.policies.contracts import CommandStatus, RecordUsageAction
from mission_control.interfaces.socketio.app import MissionSocketConfig, mount_mission_socketio
from mission_control.interfaces.socketio.server import STREAM_SERVICES, MissionSocketLimits
from tests.fixtures.mission_control_common_db import COMPONENT_VERSION, CommonDatabase
from tests.support.db_builders import AdmittedUnit, admit_unit_attempt, owner_rows, scoped_command
from tests.support.run_control import ALL_PERMISSIONS
from tests.unit.socketio.harness import serve

DSN_ENV = "MC_SOCKET_TEST_DSN"
ISSUER = "https://issuer.invalid"
ORIGIN = "http://dashboard.test"
REDIS_ENV = "MISSION_CONTROL_TEST_REDIS_URL"
FAST = PumpSettings(page_size=50, poll_interval=0.2, slow_consumer_grace=1.0)


@dataclass
class Stack:
    db: CommonDatabase
    url: str
    key: RSAKey
    admitted: AdmittedUnit
    app: Any
    pool: asyncpg.Pool
    pool_opens: list[int]

    def token(
        self, subject: str, *, tenant: str = "tenant-1", ttl: float = 300, **claims: Any
    ) -> str:
        body = {
            "sub": subject,
            "iss": ISSUER,
            "aud": "authenticated",
            "exp": int(time.time() + ttl),
            "app_metadata": {
                "application_id": "biotech",
                "tenant_id": str(self.db.tenants[tenant]),
            },
        }
        body.update(claims)
        return jwt.encode({"alg": "RS256", "kid": "socket"}, body, self.key)

    async def last_seq(self) -> int:
        rows = await owner_rows(
            self.db,
            "SELECT m.last_event_seq FROM mission_control.mission m "
            "JOIN mission_control.mission_run r USING (installation_id, application_id, "
            "tenant_id, mission_id) WHERE r.run_key = $1",
            self.admitted.run_key,
        )
        return int(rows[0]["last_event_seq"])

    async def record_usage(self, count: int, *, pause: float = 0.0) -> list[int]:
        authority = self.admitted.run_control
        for _ in range(count):
            current = await authority.get_run(self.db.scope(), self.admitted.run_key)
            decision = await authority.execute(
                scoped_command(
                    self.db,
                    self.admitted.run_key,
                    current.version,
                    f"usage-{uuid4()}",
                    RecordUsageAction(
                        usage_id=f"usage:{uuid4()}", reservation_id="baseline", actual_amounts={}
                    ),
                )
            )
            assert decision.status == CommandStatus.ACCEPTED, decision
            if pause:
                await asyncio.sleep(random.uniform(0, pause))
        return [await self.last_seq()]


def binding(db: CommonDatabase) -> ApplicationBinding:
    return ApplicationBinding.seal(
        application_id=db.application_id,
        installation_id=db.installation_id,
        binding_version="1",
        supabase_project_ref=db.project_ref,
        database_secret_ref=DSN_ENV,
        accepted_issuers={ISSUER},
        accepted_audiences={"authenticated"},
        required_component_version=COMPONENT_VERSION,
    )


def deployment(db: CommonDatabase, public_jwks: Any) -> MissionDeployment:
    reader = {"workflow_run.read"}
    auth = ApplicationAuthentication(
        binding=binding(db),
        issuer=ISSUER,
        audience="authenticated",
        public_jwks_file=public_jwks,
        grants=(
            ActorGrant(
                subject="operator",
                actor_id="operator",
                tenant_ids={db.tenants["tenant-1"]},
                permissions=ALL_PERMISSIONS | reader,
                # The lifecycle authority a pause decision names (realtime receipt proof).
                authority_refs=frozenset({"authority:lifecycle"}),
            ),
            ActorGrant(
                subject="viewer",
                actor_id="viewer",
                tenant_ids={db.tenants["tenant-1"]},
                permissions=reader,
            ),
            ActorGrant(
                subject="intruder",
                actor_id="intruder",
                tenant_ids={db.tenants["tenant-2"]},
                permissions=ALL_PERMISSIONS | reader,
            ),
        ),
    )
    return MissionDeployment(
        storage_mode="production_common",
        max_request_bytes=1_000_000,
        applications=(ApplicationDeployment(authentication=auth),),
    )


def register_streams(app: Any, db: CommonDatabase, pool: asyncpg.Pool) -> None:
    """What the proposed `bootstrap/realtime.py` does per (installation, app, tenant)."""

    registry = getattr(app.state, STREAM_SERVICES)
    for tenant in ("tenant-1", "tenant-2"):
        scope = db.scope(tenant)
        registry[(db.installation_id, db.application_id, db.tenants[tenant])] = (
            MissionStreamService(PostgresStreamSource(pool, scope), request_scope=scope)
        )


@asynccontextmanager
async def stack(
    db: CommonDatabase,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    limits: MissionSocketLimits | None = None,
    redis_url: str | None = None,
    redis_channel: str = "mission-control-socketio",
    hints: Any = None,
    key: RSAKey | None = None,
    admitted: AdmittedUnit | None = None,
) -> AsyncIterator[Stack]:
    monkeypatch.setenv(DSN_ENV, db.dsn("mission_control_runtime"))
    key = key or RSAKey.generate_key(2048, parameters={"kid": "socket"})
    public = tmp_path / f"keys-{uuid4().hex}.json"
    public.write_text(json.dumps({"keys": [key.as_dict(private=False)]}))
    opens: list[int] = []
    original = api_module.application_pool

    async def counted(secret_ref: str) -> asyncpg.Pool:
        opens.append(1)
        return await original(secret_ref)

    monkeypatch.setattr(api_module, "application_pool", counted)
    pool = await db.pool(max_size=6)
    try:
        admitted = admitted or await admit_unit_attempt(pool, db)
        app = api_module.create_application(deployment(db, public))
        config = MissionSocketConfig(
            allowed_origins=(ORIGIN,),
            redis_url=redis_url,
            redis_channel=redis_channel,
            limits=limits or MissionSocketLimits(pump=FAST),
        )
        asgi = mount_mission_socketio(app, config, hints=hints)
        register_streams(app, db, pool)
        async with serve(asgi) as (url, _server):
            yield Stack(db, url, key, admitted, app, pool, opens)
    finally:
        await pool.close()


def subscribe(run_key: str, cursor: int | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": f"req-{uuid4()}",
        "application_id": "biotech",
        "target": {"kind": "run", "id": run_key},
        "streams": ["mission_events"],
    }
    if cursor is not None:
        body["cursors"] = [mission(cursor)]
    body.update(extra)
    return body


def mission(seq: int) -> dict[str, Any]:
    return {"stream": "mission_events", "position": str(seq), "generation": None}


def auth(token: str) -> dict[str, str]:
    return {"application_id": "biotech", "token": token}

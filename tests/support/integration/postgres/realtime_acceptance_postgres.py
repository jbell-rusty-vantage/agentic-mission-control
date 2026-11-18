"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_realtime_acceptance_postgres.py.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from tests.support.db import CommonDatabase
from tests.support.db_builders import owner_rows
from tests.unit.socketio.harness import MissionClient


class RealtimeClient(MissionClient):
    """Also records the `lineage` and `human_task_receipt` events."""

    def __init__(self) -> None:
        super().__init__()
        for name in ("lineage", "human_task_receipt"):
            self.sio.on(name, self._recorder(name), namespace="/missions")


def frames_subscription(execution: str, cursor: int | None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": f"req-{uuid4()}",
        "application_id": "biotech",
        "target": {"kind": "execution", "id": execution},
        "streams": ["provider_frames"],
    }
    if cursor is not None:
        body["cursors"] = [
            {"stream": "provider_frames", "position": f"{execution}:{cursor}", "generation": 1}
        ]
    body.update(extra)
    return body


async def mission_of(db: CommonDatabase, run_key: str) -> UUID:
    rows = await owner_rows(
        db, "SELECT mission_id FROM mission_control.mission_run WHERE run_key = $1", run_key
    )
    return UUID(str(rows[0]["mission_id"]))


async def link_missions(db: CommonDatabase, upstream: UUID, downstream: UUID) -> UUID:
    tenant = db.tenants["tenant-1"]
    chain_id, link_id = uuid4(), uuid4()
    connection = await __import__("asyncpg").connect(db.owner_dsn)
    try:
        await connection.execute(
            """
            INSERT INTO mission_control.mission_chain (installation_id, application_id,
              tenant_id, chain_id, chain_key, title, manifest_digest, lifecycle, phase, members,
              version, created_at, updated_at, created_by_actor_ref)
            VALUES ($1, $2, $3, $4, $5, 'realtime proof', $6, 'running', 'releasing',
              $7::jsonb, 1, now(), now(), 'operator')
            """,
            db.installation_id,
            db.application_id,
            tenant,
            chain_id,
            f"chain-{chain_id.hex[:8]}",
            "sha256:" + "c" * 64,
            json.dumps(
                [
                    {
                        "mission_key": key,
                        "mission_id": str(mission),
                        "revision_id": str(uuid4()),
                        "order": order,
                    }
                    for order, (key, mission) in enumerate(
                        (("upstream", upstream), ("downstream", downstream))
                    )
                ]
            ),
        )
        await connection.execute(
            """
            INSERT INTO mission_control.chain_link (installation_id, application_id, tenant_id,
              link_id, chain_id, link_key, from_mission_key, to_mission_key, from_mission_id,
              to_mission_id, kind, bindings, release_condition, on_upstream_cancel,
              on_upstream_not_accepted, state, version, created_at, updated_at,
              created_by_actor_ref)
            VALUES ($1, $2, $3, $4, $5, 'downstream', 'upstream', 'downstream', $6, $7,
              'depends_on', '[]'::jsonb, '{"kind": "execution_complete"}'::jsonb, 'detach',
              'stop', 'armed', 1, now(), now(), 'operator')
            """,
            db.installation_id,
            db.application_id,
            tenant,
            link_id,
            chain_id,
            upstream,
            downstream,
        )
    finally:
        await connection.close()
    return link_id


async def release_link(db: CommonDatabase, link_id: UUID, run_key: str) -> None:
    connection = await __import__("asyncpg").connect(db.owner_dsn)
    try:
        await connection.execute(
            """
            UPDATE mission_control.chain_link link SET state = 'released', released_at = now(),
              released_run_id = run.run_id, version = link.version + 1, updated_at = now()
            FROM mission_control.mission_run run
            WHERE link.link_id = $1 AND run.run_key = $2
            """,
            link_id,
            run_key,
        )
    finally:
        await connection.close()

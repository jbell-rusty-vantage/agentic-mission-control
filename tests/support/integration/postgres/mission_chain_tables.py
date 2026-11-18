"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_mission_chain_tables.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from mission_control.domain.composition.chain import ChainScope, MissionChain

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/fixtures/manifests/two-mission-chain.yml"
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


async def insert_mission(connection: asyncpg.Connection, scope: ChainScope, key: str) -> UUID:
    mission_id = uuid4()
    await connection.execute(
        """
        INSERT INTO mission_control.mission (installation_id, application_id, tenant_id,
            mission_id, mission_key, title, owner_actor_ref, lifecycle, next_event_seq,
            version, updated_at, last_event_seq, created_at, created_by_actor_ref)
        VALUES ($1, $2, $3, $4, $5, $5, 'actor:owner', 'draft', 1, 1, $6, 0, $6, 'actor:owner')
        """,
        scope.installation_id,
        scope.application_id,
        scope.tenant_id,
        mission_id,
        key,
        NOW,
    )
    return mission_id


async def insert_chain(connection: asyncpg.Connection, chain: MissionChain) -> None:
    scope = chain.scope
    await connection.execute(
        """
        INSERT INTO mission_control.mission_chain (installation_id, application_id, tenant_id,
            chain_id, chain_key, title, manifest_digest, lifecycle, phase, terminal_outcome,
            members, version, created_at, updated_at, created_by_actor_ref)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL, $10::jsonb, 1, $11, $11, $12)
        """,
        scope.installation_id,
        scope.application_id,
        scope.tenant_id,
        chain.chain_id,
        chain.chain_key,
        chain.title,
        chain.manifest_digest,
        chain.lifecycle.value,
        chain.phase.value,
        json.dumps([member.model_dump(mode="json") for member in chain.members]),
        chain.created_at,
        chain.created_by_actor_ref,
    )
    for link in chain.links:
        await connection.execute(
            """
            INSERT INTO mission_control.chain_link (installation_id, application_id, tenant_id,
                link_id, chain_id, link_key, from_mission_key, to_mission_key, from_mission_id,
                to_mission_id, kind, bindings, release_condition, on_upstream_cancel,
                on_upstream_not_accepted, state, version, created_at, updated_at,
                created_by_actor_ref)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14,
                $15, $16, 1, $17, $17, $18)
            """,
            scope.installation_id,
            scope.application_id,
            scope.tenant_id,
            link.link_id,
            chain.chain_id,
            link.link_key,
            link.from_mission_key,
            link.to_mission_key,
            link.from_mission_id,
            link.to_mission_id,
            link.kind.value,
            json.dumps([binding.model_dump(mode="json") for binding in link.bindings]),
            json.dumps(link.on.model_dump(mode="json", exclude_none=True)),
            link.on_upstream_cancel.value,
            link.on_upstream_not_accepted,
            link.state.value,
            chain.created_at,
            chain.created_by_actor_ref,
        )

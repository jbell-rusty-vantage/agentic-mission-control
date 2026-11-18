"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_provider_lineage_postgres.py.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.db_builders import owner_rows


async def identity_rows(db: CommonDatabase, harness_execution_id: UUID) -> dict[str, Any]:
    execution = await owner_rows(
        db,
        "SELECT lifecycle FROM mission_control.harness_execution WHERE harness_execution_id = $1",
        harness_execution_id,
    )
    sessions = await owner_rows(
        db,
        "SELECT session_id, state FROM mission_control.agent_session "
        "WHERE harness_execution_id = $1",
        harness_execution_id,
    )
    turns = await owner_rows(
        db,
        "SELECT t.turn_no, t.native_turn_ref, t.usage::text AS usage "
        "FROM mission_control.session_turn t JOIN mission_control.agent_session s "
        "ON s.session_id = t.session_id WHERE s.harness_execution_id = $1 ORDER BY t.turn_no",
        harness_execution_id,
    )
    return {
        "lifecycle": execution[0]["lifecycle"],
        "sessions": [row["state"] for row in sessions],
        "turns": [
            (row["turn_no"], row["native_turn_ref"], json.loads(row["usage"])) for row in turns
        ],
    }


def tokens(usage: dict[str, Any], dimension: str) -> Any:
    return usage["dimensions"][dimension]["value"]

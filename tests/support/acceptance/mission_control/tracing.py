"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_tracing.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from mission_control.adapters.postgres.scope import apply_scope
from mission_control.contracts.identities import mission_root_id
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.scoped_api_stack import ScopedStack, inspect
from tests.support.acceptance.mission_control.cognition_points import BASE

TRACING = technical.TRACING_FAMILY


EVIDENCE_ROOT = Path(".scratch/tracing-stage-1")


def as_json(value: Any) -> Any:
    """A jsonb column as asyncpg returns it without a codec (text) -> Python."""

    return json.loads(value) if isinstance(value, str | bytes) else value


async def db_rows(stack: ScopedStack, sql: str, *args: Any) -> list[dict[str, Any]]:
    """Rows of one owner-role read of the common database under the stack's tenant context.

    The owner pool is subject to the forced row-level security of the common component, so
    the `mc.installation_id` / `mc.application_id` / `mc.tenant_id` settings are bound for
    the transaction the way `mission_control_common_db._insert_tenants` binds them; the
    canonical scope `mc/{installation}/{application}/{tenant}` carries all three.
    """

    async with stack.owner_pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, stack.scope)
        rows = await connection.fetch(sql, *args)
    return [dict(row) for row in rows]


def _write_evidence(name: str, payload: dict[str, Any]) -> Path:
    path = EVIDENCE_ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


async def temporal_diagnostics(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every Temporal workflow of the run with its status and, when closed badly, the failure
    message of its last history event (the family workflow's `ApplicationError`)."""

    rows: list[dict[str, Any]] = []
    async for description in stack.client.list_workflows(
        f"WorkflowId STARTS_WITH '{mission_root_id(stack.scope, run_id)}'"
    ):
        row: dict[str, Any] = {
            "workflow_id": description.id,
            "type": description.workflow_type,
            "status": str(description.status),
        }
        if description.status is not None and description.status.name not in {
            "RUNNING",
            "COMPLETED",
        }:
            handle = stack.client.get_workflow_handle(description.id, run_id=description.run_id)
            history = await handle.fetch_history()
            last = history.events[-1]
            row["last_event"] = str(last)[-3000:]
        rows.append(row)
    return rows


def _excerpt(value: Any) -> tuple[str, Any]:
    """A `provider_frame.body_excerpt` (bytea) as text and, when it parses, as JSON."""

    if isinstance(value, bytes | bytearray):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    try:
        return text, json.loads(text)
    except ValueError:
        return text, None


async def frames_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The run's `provider_frame` rows joined to their unit (`activation.activation_key`), in
    arrival order per harness execution; `body` is the excerpt parsed as JSON when it is."""

    rows = await db_rows(
        stack,
        """
        SELECT f.frame_id::text AS frame_id, f.activation_id::text AS activation_id,
               a.activation_key AS unit_key, f.attempt_no,
               f.harness_execution_id::text AS harness_execution_id, f.generation,
               f.provider_key, f.arrival_ordinal, f.kind, f.raw_kind, f.closing,
               f.subordinate_ref, f.tool_call_ref, f.body_digest, f.body_bytes,
               f.body_media_type, f.body_excerpt, f.body_artifact_ref, f.native_session_ref,
               f.native_turn_ref, f.observed_at
        FROM mission_control.provider_frame AS f
        JOIN mission_control.activation AS a
          ON a.installation_id = f.installation_id
         AND a.application_id = f.application_id
         AND a.tenant_id = f.tenant_id
         AND a.activation_id = f.activation_id
        WHERE f.run_id = (SELECT run_id FROM mission_control.mission_run WHERE run_key = $1)
        ORDER BY f.harness_execution_id, f.arrival_ordinal
        """,
        run_id,
    )
    for row in rows:
        row["excerpt"], row["body"] = _excerpt(row.pop("body_excerpt"))
    return rows


async def transcript_entries(
    stack: ScopedStack, run_id: str, *, full: bool = False, **params: Any
) -> list[dict[str, Any]]:
    """Every transcript entry of the run (`GET runs/{id}/transcript?format=json`, paged by
    cursor; the route streams NDJSON unless `format=json` or an `application/json` accept)."""

    entries: list[dict[str, Any]] = []
    since: str | None = None
    while True:
        query: dict[str, Any] = {"limit": 5000, "format": "json", **params}
        if full:
            query["full"] = "true"
        if since:
            query["since"] = since
        response = await stack.http.get(f"{BASE}/{run_id}/transcript", params=query)
        assert response.status_code == 200, (response.status_code, response.text[:800])
        page = response.json()
        entries.extend(page["entries"])
        if not page.get("has_more") or not page.get("next_cursor"):
            return entries
        since = page["next_cursor"]


async def settlements_for_run(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """The latest settlement of every claimed operation: `(operation id, status, usage)`."""

    rows = await db_rows(
        stack,
        """
        SELECT DISTINCT ON (c.semantic_attempt_key)
               c.semantic_attempt_key, s.status, s.usage_payload
        FROM mission_control.operation_claim AS c
        JOIN mission_control.operation_settlement AS s
          ON (s.installation_id, s.application_id, s.tenant_id, s.claim_key)
           = (c.installation_id, c.application_id, c.tenant_id, c.claim_key)
        WHERE c.run_key = $1
        ORDER BY c.semantic_attempt_key, s.settlement_revision DESC
        """,
        run_id,
    )
    return [
        {
            "operation": row["semantic_attempt_key"].split(":operation:", 1)[-1],
            "status": row["status"],
            "usage": as_json(row["usage_payload"]),
        }
        for row in rows
    ]


def find_keys(value: Any, name: str, found: list[Any] | None = None) -> list[Any]:
    """Every value under a key called `name`, anywhere in a JSON document."""

    found = [] if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name:
                found.append(item)
            find_keys(item, name, found)
    elif isinstance(value, list):
        for item in value:
            find_keys(item, name, found)
    return found


async def terminal(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    return state["lifecycle"] in {"completed", "cancelled", "failed"}


async def cancel_immediately(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    """`cancel` with `urgency: immediate` over the commands route, re-reading a stale version."""

    body: dict[str, Any] = {}
    response = None
    for _attempt in range(12):
        state = await inspect(stack, run_id)
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": "cancel",
            "payload": {"urgency": "immediate"},
            "reason": "FX-TR-HOOK: stop fence",
        }
        response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
        if response.status_code == 202:
            return body
        assert response.status_code == 409, response.text
    raise AssertionError(f"cancel never accepted: {response.text if response else 'no response'}")


def missionctl(url: str, token: str, *args: str) -> subprocess.Popen[bytes]:
    """A separate `missionctl` process (the Windows selector loop cannot spawn asyncio ones)."""

    return subprocess.Popen(
        [sys.executable, "-m", "mission_control.interfaces.cli", *args],
        env={
            **os.environ,
            "MISSION_CONTROL_URL": url,
            "MISSION_CONTROL_APPLICATION_ID": "biotech",
            "MISSION_CONTROL_TOKEN": token,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def cli(url: str, token: str, *args: str) -> tuple[int, str, str]:
    """One `missionctl` command over loopback HTTP: (exit code, stdout, stderr)."""

    process = missionctl(url, token, *args)
    stdout, stderr = await asyncio.to_thread(process.communicate, timeout=180)
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def parse_cli_json(out: str) -> dict[str, Any] | None:
    """The CLI's JSON document (whole stdout, or its last JSON line) when it prints one."""

    for candidate in (out, last_line(out)):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None

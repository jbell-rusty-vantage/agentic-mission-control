"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_authenticated_scoped_runtime.py.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from mission_control.contracts.identities import mission_root_id
from tests.support.stack import ScopedStack, inspect, until


async def condition(stack: ScopedStack, run_id: str, field: str, expected: Any) -> bool:
    return (await inspect(stack, run_id))[field] == expected


async def command(stack: ScopedStack, run_id: str, kind: str, payload: dict[str, Any]) -> str:
    state = await inspect(stack, run_id)
    request_id = str(uuid4())
    body = {
        "request_id": request_id,
        "expected_version": state["version"],
        "expected_generation": state["execution_generation"],
        "target": {"kind": "run", "id": run_id},
        "kind": kind,
        "payload": payload,
        "reason": "deterministic scoped HTTP qualification",
    }
    response = await stack.http.post(f"/v1/applications/biotech/runs/{run_id}/commands", json=body)
    assert response.status_code == 202, response.text
    assert response.json()["admission"]["status"] == "accepted", response.text

    async def applied() -> bool:
        result = await stack.http.get(f"/v1/applications/biotech/runs/{run_id}/commands")
        assert result.status_code == 200, result.text
        match = next(
            item
            for item in result.json()["commands"]
            if item["command"]["command_id"] == request_id
        )
        return [item["state"] for item in match["receipts"]][-1:] == ["applied"]

    await until(applied)
    replay = await stack.http.post(f"/v1/applications/biotech/runs/{run_id}/commands", json=body)
    assert replay.status_code == 200 and replay.json()["replay"] is True, replay.text
    return request_id


async def assert_persisted_run_evidence(
    stack: ScopedStack, run_id: str, terminal_outcome: str
) -> None:
    base = f"/v1/applications/biotech/runs/{run_id}"
    inputs = await stack.http.get(base + "/inputs")
    assert inputs.status_code == 200, inputs.text
    assert inputs.json()["status"] == "recorded"
    assert inputs.json()["binding"] is None
    templates = inputs.json()["native_templates"]
    assert len(templates) == 2
    assert all(item["template"]["request_scope"] == stack.scope for item in templates)
    assert all(item["document_digest"].startswith("sha256:") for item in templates)

    # A returned root result must already have its durable typed-result record.
    async with asyncio.timeout(60):
        await stack.client.get_workflow_handle(mission_root_id(stack.scope, run_id)).result()
    response = await stack.http.get(base + "/evidence")
    assert response.status_code == 200, response.text
    evidence = response.json()
    assert evidence["authority"] == "persisted_mission_control_records"
    assert evidence["run_id"] == run_id
    assert evidence["request_scope"] == stack.scope
    # Native run admission still creates the canonical mission anchor.
    assert str(UUID(evidence["mission_id"])) == evidence["mission_id"]
    assert evidence["inputs"]["status"] == "recorded"
    assert evidence["inputs"]["native_template_count"] == len(templates)
    assert evidence["inspection"]["phase"] == "terminal"
    assert evidence["inspection"]["projection"]["terminal_outcome"] == terminal_outcome
    assert evidence["result"]["status"] == "recorded", evidence["result"]
    result = evidence["result"]["record"]
    assert result["run_id"] == run_id
    assert result["request_scope"] == stack.scope
    assert result["terminal_outcome"] == terminal_outcome
    assert evidence["provider_urls_status"] == "not_collected"
    assert evidence["sandbox_state_status"] == "not_verified"
    assert evidence["artifact_bytes_status"] == "not_verified"

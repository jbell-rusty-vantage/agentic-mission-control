"""Ordinary scoped controls for the Qualia fixture, with retained request/receipt evidence.

Prepare a successor manifest through the actual submit service, then call the production
launch author's ``family_input`` for its unstarted run. That freezes exact target-ERC
templates under ``semantic-input:manifest:<prepared run>``. Pass that family input and
reference to ``fork_prepared_stage``. The returned launch request uses the recorded source
point, new admitted ERC and prepared sealed capability bindings. Changing ERC invalidates
all earlier work; it does not claim reuse. The source mission and its templates stay intact.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal
from uuid import uuid4

import httpx


def _base(application_id: str, run_id: str) -> str:
    return f"/v1/applications/{application_id}/runs/{run_id}"


async def _observe(
    http: httpx.AsyncClient,
    method: str,
    path: str,
    records: list[dict[str, Any]],
    *,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    response = (
        await http.request(method, path, json=body) if body is not None else await http.get(path)
    )
    records.append(
        {
            "method": method,
            "path": path,
            "request": deepcopy(body),
            "status": response.status_code,
            "response": response.json(),
        }
    )
    return response


async def send_stage_command(
    http: httpx.AsyncClient,
    *,
    application_id: str,
    run_id: str,
    node_key: str,
    text: str,
    kind: Literal["queue_instruction", "interrupt_and_inject"],
    records: list[dict[str, Any]],
    retries: int = 12,
) -> dict[str, Any]:
    """Admit a node-targeted command; delivery is a separate persisted proof."""
    base = _base(application_id, run_id)
    for _ in range(retries):
        inspection = await _observe(http, "GET", f"{base}/inspection", records)
        inspection.raise_for_status()
        state = inspection.json()
        payload: dict[str, Any] = {"content": {"text": text}, "node_key": node_key}
        if kind == "queue_instruction":
            payload["boundary"] = "next_turn"
        else:
            payload["settle_uncertain_effects"] = True
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": kind,
            "payload": payload,
            "reason": f"Qualia fixture: {kind} for {node_key}",
        }
        response = await _observe(http, "POST", f"{base}/commands", records, body=body)
        if response.status_code in {200, 202}:
            return response.json()
        answer = response.json()
        code = answer.get("detail", {}).get("code")
        stale = code in {"stale_version", "stale_generation"} or (
            answer.get("admission", {}).get("status") == "stale"
        )
        if response.status_code != 409 or not stale:
            response.raise_for_status()
    raise AssertionError(f"{kind} never admitted after {retries} fresh inspections")


async def collect_control_receipts(
    http: httpx.AsyncClient,
    *,
    application_id: str,
    run_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    response = await _observe(http, "GET", f"{_base(application_id, run_id)}/commands", records)
    response.raise_for_status()
    return response.json()


async def fork_prepared_stage(
    http: httpx.AsyncClient,
    *,
    application_id: str,
    source_run_id: str,
    snapshot: dict[str, Any],
    point: dict[str, Any],
    prepared_family_input: dict[str, Any],
    prepared_input_manifest: dict[str, Any],
    prepared_binding_ref: str,
    instruction: str,
    sponsorship_ref: str,
    approval_refs: list[str],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Fork from a recorded stage/checkpoint, returning a concrete ordinary launch call.

    The caller launches only after retaining this result, then proves actual target skill
    materialization and message consumption from saved runtime/transcript records.
    """
    if snapshot["source_run_id"] != source_run_id or not point.get("seedable"):
        raise ValueError("the fork requires this source's snapshot and a recorded seedable point")
    location, coordinate = point["location"], point["coordinate"]
    if location["family"] != "stage_graph" or coordinate["point"]["kind"] != "checkpoint":
        raise ValueError("the fork point must identify a StageGraph checkpoint")
    if coordinate["run_id"] != source_run_id:
        raise ValueError("the fork point belongs to another source run")
    target_digest = prepared_family_input["effective_configuration_digest"]
    if target_digest == snapshot["effective_configuration_digest"]:
        raise ValueError("the prepared Tavily configuration must have its own ERC digest")
    fork_body = {
        "request_id": str(uuid4()),
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_digest": snapshot["snapshot_digest"],
        "at": {"stage": location["node_key"], "cycle": location["cycle"]},
        "cognitive_seed": {
            "unit_key": coordinate["unit_key"],
            "checkpoint": coordinate["point"]["key"],
        },
        "changes": [
            {"path": "effective_configuration_digest", "value": target_digest},
            {"path": "input_manifest", "value": deepcopy(prepared_input_manifest)},
        ],
        "invalidation_frontier": ["*"],
        "message": {"text": instruction},
        "sponsorship_ref": sponsorship_ref,
        "approval_refs": approval_refs,
        "reason": "Qualia fixture: fork recorded stage with prepared Tavily configuration",
    }
    path = f"{_base(application_id, source_run_id)}/forks"
    response = await _observe(http, "POST", path, records, body=fork_body)
    response.raise_for_status()
    result = response.json()
    receipt = result["receipt"]
    derived_run = receipt["target_run_id"]
    inspection = await _observe(
        http, "GET", f"{_base(application_id, derived_run)}/inspection", records
    )
    inspection.raise_for_status()
    family_input = deepcopy(prepared_family_input)
    family_input.update(
        run_id=derived_run,
        initial_run_version=inspection.json()["version"],
        execution_epoch=1,
        semantic_input_binding_ref=f"semantic-input:fork:{receipt['request_id']}",
    )
    start = receipt.get("start_position")
    if start is not None:
        family_input["start_position"] = {
            "workflow_cycle_ordinal": start.get("workflow_cycle_ordinal") or 0,
            "stage_cycle_ordinals": start.get("stage_cycle_ordinals") or {},
            "stage_objectives": start.get("stage_objectives") or {},
        }
    return {
        "fork": result,
        "launch_path": f"{_base(application_id, derived_run)}/launch",
        "launch_body": {
            "family": "StageGraph",
            "stagegraph": family_input,
            "source_semantic_input_binding_ref": prepared_binding_ref,
        },
        "earlier_stages_reused": False,
    }

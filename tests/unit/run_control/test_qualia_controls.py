from __future__ import annotations

import json
from typing import Any, Literal

import httpx
import pytest

from tests.fixtures.qualia_controls import fork_prepared_stage, send_stage_command


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["queue_instruction", "interrupt_and_inject"])
@pytest.mark.parametrize("stale_form", ["detail", "receipt"])
async def test_stage_commands_refresh_stale_inspection_and_retain_admission_evidence(
    kind: Literal["queue_instruction", "interrupt_and_inject"],
    stale_form: str,
) -> None:
    posts: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"version": len(posts) + 1, "execution_generation": 2})
        body = json.loads(request.content)
        posts.append(body)
        if len(posts) == 1:
            return httpx.Response(
                409,
                json={"detail": {"code": "stale_version"}}
                if stale_form == "detail"
                else {"admission": {"status": "stale"}},
            )
        return httpx.Response(202, json={"request_id": body["request_id"], "delivery": None})

    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://local"
    ) as http:
        result = await send_stage_command(
            http,
            application_id="biotech",
            run_id="source",
            node_key="research",
            text="Preserve exact label citations.",
            kind=kind,
            records=records,
        )
    assert posts[0]["request_id"] != posts[1]["request_id"]
    assert [body["expected_version"] for body in posts] == [1, 2]
    assert posts[-1]["payload"]["node_key"] == "research"
    assert posts[-1]["expected_generation"] == 2
    assert result["delivery"] is None
    assert [row["status"] for row in records] == [200, 409, 200, 202]
    if kind == "queue_instruction":
        assert posts[-1]["payload"]["boundary"] == "next_turn"
    else:
        assert posts[-1]["payload"]["settle_uncertain_effects"] is True


@pytest.mark.asyncio
async def test_prepared_fork_keeps_recorded_point_and_uses_target_templates_without_mutation() -> (
    None
):
    bodies = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"version": 1})
        bodies.append(json.loads(request.content))
        return httpx.Response(
            202,
            json={
                "receipt": {
                    "request_id": "scoped-fork-request",
                    "target_run_id": "derived",
                    "start_position": {"stage_cycle_ordinals": {"research": 0}},
                    "message_delivery": "seed_head",
                }
            },
        )

    snapshot = {
        "source_run_id": "source",
        "snapshot_id": "run-snapshot:source",
        "snapshot_digest": "sha256:" + "a" * 64,
        "effective_configuration_digest": "sha256:" + "b" * 64,
    }
    point = {
        "seedable": True,
        "location": {"family": "stage_graph", "node_key": "research", "cycle": 0},
        "coordinate": {
            "run_id": "source",
            "unit_key": "source-unit",
            "point": {"kind": "checkpoint", "key": {"checkpoint_id": "actual-checkpoint"}},
        },
    }
    prepared = {
        "run_id": "prepared",
        "effective_configuration_digest": "sha256:" + "c" * 64,
        "semantic_input_binding_ref": "semantic-input:manifest:prepared",
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), base_url="http://local"
    ) as http:
        result = await fork_prepared_stage(
            http,
            application_id="biotech",
            source_run_id="source",
            snapshot=snapshot,
            point=point,
            prepared_family_input=prepared,
            prepared_input_manifest={"digest": "sha256:" + "d" * 64},
            prepared_binding_ref="semantic-input:manifest:prepared",
            instruction="Use the prepared Tavily skill and preserve exact citations.",
            sponsorship_ref="sponsorship:test",
            approval_refs=[],
            records=[],
        )
    assert bodies[0]["invalidation_frontier"] == ["*"]
    assert bodies[0]["changes"][1] == {
        "path": "input_manifest",
        "value": {"digest": "sha256:" + "d" * 64},
    }
    assert bodies[0]["at"] == {"stage": "research", "cycle": 0}
    assert bodies[0]["cognitive_seed"]["checkpoint"]["checkpoint_id"] == "actual-checkpoint"
    launch = result["launch_body"]
    assert launch["source_semantic_input_binding_ref"] == "semantic-input:manifest:prepared"
    assert (
        launch["stagegraph"]["semantic_input_binding_ref"]
        == "semantic-input:fork:scoped-fork-request"
    )
    assert (
        launch["stagegraph"]["effective_configuration_digest"]
        == prepared["effective_configuration_digest"]
    )
    assert launch["stagegraph"]["run_id"] == "derived"
    assert result["earlier_stages_reused"] is False
    assert prepared["run_id"] == "prepared"

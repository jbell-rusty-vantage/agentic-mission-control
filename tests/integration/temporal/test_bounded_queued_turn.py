"""Real signed HTTP + PostgreSQL + Temporal: queue a running bounded Deep Agents stage."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mission_control.bootstrap.settings import get_settings
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.scoped_api_stack import admit_and_launch, inspect, scoped_stack, until
from tests.integration.temporal.test_manifest_launch_production import host_pins

pytestmark = pytest.mark.common_db
MARKER = "SIGNED-QUEUED-NATIVE-TURN-2fcb97"


def test_running_stage_receives_queue_in_same_session_before_canonical_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    asyncio.run(_prove(tmp_path, monkeypatch), loop_factory=loop_factory)


async def _prove(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", "biotech")
    get_settings.cache_clear()
    monkeypatch.setenv("CAPABILITY_PINS_PATH", str(host_pins(root / "capability-pins.json")))
    # Explicit authored fixture authority for both native turns, including sync children.
    monkeypatch.setattr(technical, "UNIT_RESERVATION", {"tokens.total": 80, "model.turns": 16})
    initial = technical.stage_blueprint()
    monkeypatch.setattr(
        technical,
        "stage_blueprint",
        lambda: initial.model_copy(
            update={
                "stages": (initial.stages[0],),
                "dependencies": (),
                "joins": (),
                "waits": (),
            }
        ),
    )
    entered, release = asyncio.Event(), asyncio.Event()
    visible: list[list[str]] = []
    generate = technical.TechnicalModel._agenerate

    async def model_call(self: Any, messages: Any, *args: Any, **kwargs: Any) -> Any:
        if not entered.is_set():
            entered.set()
            await release.wait()
        visible.append([str(item.content) for item in messages if item.type == "human"])
        return await generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(technical.TechnicalModel, "_agenerate", model_call)
    async with scoped_stack(root, monkeypatch) as stack:
        run_id, root_id = await admit_and_launch(stack, "StageGraph")
        await asyncio.wait_for(entered.wait(), 60)
        state = await inspect(stack, run_id)
        request_id = str(uuid4())
        command = await stack.http.post(
            f"/v1/applications/biotech/runs/{run_id}/commands",
            json={
                "request_id": request_id,
                "expected_version": state["version"],
                "expected_generation": state["execution_generation"],
                "target": {"kind": "run", "id": run_id},
                "kind": "queue_instruction",
                "payload": {
                    "node_key": "draft",
                    "boundary": "next_turn",
                    "content": {"text": MARKER},
                },
                "reason": "prove a real queued native follow-up before this stage finalizes",
            },
        )
        assert command.status_code == 202, command.text
        assert command.json()["admission"]["status"] == "accepted", command.text
        release.set()

        async def completed() -> bool:
            observed = await inspect(stack, run_id)
            if observed["phase"] == "terminal":
                assert observed["execution_outcome"] == "completed", observed
                return True
            return False

        try:
            await until(completed, seconds=240)
            handle = stack.client.get_workflow_handle(root_id)
            assert (await handle.describe()).workflow_type == "mc.mission_run.v1"
            await asyncio.wait_for(handle.result(), 30)
            response = await stack.http.get(f"/v1/applications/biotech/runs/{run_id}/commands")
            response.raise_for_status()
            commands = response.json()
            record = next(
                item for item in commands["commands"] if item["command"]["command_id"] == request_id
            )
            assert record["receipts"][-1]["state"] == "applied", record
            assert any(MARKER in text for call in visible for text in call)
            assert all(sum(MARKER in text for text in call) <= 1 for call in visible)
            reports = [
                item["delivery_report"]
                for item in record["receipts"]
                if item.get("delivery_report")
            ]
            assert all(
                item["delivered_semantics"] == "turn_boundary_guaranteed" for item in reports
            )
            assert all(item["native_refs"]["cancelled_turn_ref"] is None for item in reports)
            state = await inspect(stack, run_id)
            assert len(state["projection"]["accepted_output_evidence"]) == 1
            assert (
                next(
                    item["consumed"]
                    for item in state["budget"]["dimensions"]
                    if item["dimension"] == "tokens.total"
                )
                == 50
            )
        finally:
            release.set()
            (root / "bounded-queued-turn-proof.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "root_id": root_id,
                        "command": command.json(),
                        "inspection": await inspect(stack, run_id),
                        "visible_human_messages": visible,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )

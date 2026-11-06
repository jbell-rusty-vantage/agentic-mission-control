"""Run 2 Cursor regression evidence; deterministic providers only."""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.cursor.cloud_api import AgentNotFound
from mission_control.application.execution.harness.protocol import NativeTurnLost
from mission_control.domain.execution.lanes import CancelTurnRequest, TurnHandle
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import harness_fields, started_session
from tests.fixtures.cursor_local import local_stack
from tests.unit.cursor.support import send_request


@pytest.mark.parametrize("profile", ["cursor_local", "cursor_cloud"])
async def test_required_staged_prompt_never_resends_original(tmp_path: Path, profile: str) -> None:
    stack = local_stack(tmp_path) if profile == "cursor_local" else cloud_stack(tmp_path)
    heid, session = await started_session(stack)
    request = send_request(stack, profile, heid, str(session.native_session_ref), 2)
    with pytest.raises(NativeTurnLost, match="staged turn"):
        await stack.harness.send_turn(request.model_copy(update={"instruction_ref": "lost"}))
    stack.harness.stage_turn(heid, "empty-authored", "")
    staged = stack.harness._sessions[heid]
    assert staged.turn_texts["empty-authored"] == ""


async def test_cloud_continuation_preserves_admitted_body_and_archives_source(
    tmp_path: Path,
) -> None:
    stack = cloud_stack(tmp_path)
    heid, session = await started_session(stack)
    source = str(session.native_session_ref)
    target, _ = await stack.harness.hydrate_agent(
        heid,
        transfer_id="t",
        files=[],
        prompt="Continue exact staged prompt",
        source_session_ref=source,
    )
    first, continuation = stack.api.creates[0], stack.api.creates[-1]
    for key in (
        "model",
        "repos",
        "mode",
        "metadata",
        "mcpServers",
        "env",
        "envVars",
        "customSubagents",
    ):
        assert first.get(key) == continuation.get(key), key
    assert continuation["prompt"]["text"] == "Continue exact staged prompt"
    await stack.harness.complete_handover(heid, "wrong")
    assert stack.harness._sessions[heid].session_ref == source
    await stack.harness.complete_handover(heid, "t")
    assert stack.harness._sessions[heid].session_ref == target
    archives = [r for r in stack.api.requests if r.url.path.endswith("/archive")]
    assert len(archives) == 1 and source in archives[0].url.path
    await stack.harness.complete_handover(heid, "t")
    assert len([r for r in stack.api.requests if r.url.path.endswith("/archive")]) == 1


async def test_cancel_ack_survives_run_disappearing_after_cancel(
    tmp_path: Path, monkeypatch
) -> None:
    stack = cloud_stack(tmp_path)
    heid, session = await started_session(stack)
    run = TurnHandle(session=session, turn_no=1, native_turn_ref=stack.api.run_id)

    async def gone(*args):
        raise AgentNotFound("gone")

    monkeypatch.setattr(stack.client, "get_run", gone)
    receipt = await stack.harness.cancel_turn(
        CancelTurnRequest(
            **harness_fields(stack.operation, heid, "cursor_cloud"),
            turn=run,
            reason="test",
            urgency="immediate",
        )
    )
    assert receipt.acknowledged and receipt.native_status == "unknown"

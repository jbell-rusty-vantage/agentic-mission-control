"""FX-TR-STREAM (tracing Stage 2 §4c, T0 first): the Socket.IO stream equals the transcript.

One client subscribes to the tracing run's `mission_events` and `provider_frames` right after
launch (deltas included) and acknowledges as it reads; after the run completes and the pumps
drain, `stream_proof` compares what it received with the projected transcript
(`tests/fixtures/stream_capture.py::compare`): unit frames carry `unit_key` and their
`after_point_ref`, unit mission events carry `unit_key` and `point_ref`, each point's frames
arrive in transcript order, and nothing is in one and not the other except listed deltas.

Then a second client resumes one execution from a point boundary in its middle: it subscribes
with the cursor of the last frame before the first frame that follows point P (the frame's
`after_point_ref`), and receives exactly the remainder of that execution. The stream has no
`after_point_ref` subscribe parameter; the point-to-cursor step is the client's, from the
envelopes it already holds.

The live run (`test_tracing_live.py`, §4 item 1) reuses `stream_proof`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.acceptance.mission_control.test_cognition_points import (
    BASE,
    all_points,
    completed,
    launch,
)
from tests.acceptance.mission_control.test_tracing import TRACING, transcript_entries
from tests.fixtures.live_models import write_json
from tests.fixtures.scoped_api_stack import ScopedStack, scoped_stack, until
from tests.fixtures.stage2_outputs import run_directory
from tests.fixtures.stream_capture import StreamCapture, compare, mission_socket, problems

pytestmark = pytest.mark.common_db


async def inject_into(stack: ScopedStack, run_id: str, node_key: str, text: str) -> dict[str, Any]:
    """`interrupt_and_inject` naming the node, re-reading a stale version."""

    from uuid import uuid4

    from tests.fixtures.scoped_api_stack import inspect

    for _attempt in range(12):
        state = await inspect(stack, run_id)
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": "interrupt_and_inject",
            "payload": {"content": {"text": text}, "node_key": node_key},
            "reason": "tracing Stage 2: inject mid-turn",
        }
        response = await stack.http.post(f"{BASE}/{run_id}/commands", json=body)
        if response.status_code == 202:
            return body
        assert response.status_code == 409, response.text
    raise AssertionError("the inject was never accepted")


def resume_point(capture: StreamCapture) -> dict[str, Any] | None:
    """The execution with the most frames and the point boundary nearest its middle."""

    by_execution: dict[str, list[dict[str, Any]]] = {}
    for name, data in capture.envelopes():
        if name == "provider_frame":
            by_execution.setdefault(data["execution_ref"], []).append(data)
    if not by_execution:
        return None
    execution, frames = max(by_execution.items(), key=lambda item: len(item[1]))
    boundaries = [
        index
        for index in range(1, len(frames))
        if (frames[index]["payload"] or {}).get("after_point_ref")
        and (frames[index]["payload"] or {}).get("after_point_ref")
        != (frames[index - 1]["payload"] or {}).get("after_point_ref")
    ]
    if not boundaries:
        return None
    middle = min(boundaries, key=lambda index: abs(index - len(frames) // 2))
    return {
        "execution_ref": execution,
        "point": frames[middle]["payload"]["after_point_ref"],
        "cursor": frames[middle - 1]["cursor"],
        "remainder": [frame["event_id"] for frame in frames[middle:]],
        "frames_in_execution": len(frames),
    }


async def stream_proof(
    stack: ScopedStack, socket_url: str, run_id: str, capture: StreamCapture
) -> dict[str, Any]:
    """Drain, compare with the transcript, then resume from a point; the evidence, unasserted."""

    await capture.settle()
    entries = await transcript_entries(stack, run_id)
    report = compare(capture.envelopes(), entries)
    report["capture_errors"] = capture.errors
    plan = resume_point(capture)
    report["resume"] = plan
    if plan is not None:
        resumed = StreamCapture(socket_url, stack.token, run_id)
        try:
            await resumed.start([plan["cursor"]])
            await resumed.settle()
            got = [
                data["event_id"]
                for name, data in resumed.envelopes()
                if name == "provider_frame" and data["execution_ref"] == plan["execution_ref"]
            ]
            report["resume"] = {
                **plan,
                "received": len(got),
                "exact_remainder": got == plan["remainder"],
            }
        finally:
            await resumed.close()
    report["problems"] = problems(report)
    return report


def assert_stream(report: dict[str, Any]) -> None:
    assert report["frames_received"] > 0, report
    assert not report["problems"], {key: report[key] for key in report["problems"]}
    assert report["resume"] and report["resume"]["exact_remainder"], report["resume"]


@pytest.mark.asyncio
async def test_fx_tr_stream_t0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        mission_socket(stack.application) as socket_url,
    ):
        run_id = await launch(stack, TRACING)
        capture = StreamCapture(socket_url, stack.token, run_id)
        await capture.start()
        try:
            await until(lambda: completed(stack, run_id), seconds=420)
            report = await stream_proof(stack, socket_url, run_id, capture)
        finally:
            await capture.close()
        write_json(run_directory("fx-tr-stream-t0", run_id) / "stream-report.json", report)
        print("FX-TR-STREAM T0", json.dumps(report, default=str)[:3000])
        assert_stream(report)


@pytest.mark.asyncio
async def test_fx_tr_reconcile_after_inject_t0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-TR-RECONCILE-LIVE's T0 twin (tracing Stage 2, F-S2-6): an `interrupt_and_inject`
    into S1's running turn, the run to completion, then `points:reconcile` writes nothing:
    the settlement already gave the interrupted turn's points their frame ranges."""

    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", "2.5")
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, TRACING)

        async def s1_running() -> bool:
            return len(stack.model_log) >= 2

        await until(s1_running, seconds=300)
        injected = await inject_into(stack, run_id, "S1", "Inject: keep the record short.")
        await until(lambda: completed(stack, run_id), seconds=420)
        before = {item["point_id"]: item.get("frames") for item in await all_points(stack, run_id)}
        response = await stack.http.post(f"{BASE}/{run_id}/points:reconcile", json={})
        assert response.status_code == 200, response.text
        report = response.json()
        after = await all_points(stack, run_id)
        filled = [
            {"roles": item["roles"], "ordinal": item["ordinal"], "frames": item.get("frames")}
            for item in after
            if item.get("frames") != before.get(item["point_id"])
        ]
        roles = {role for item in after for role in item["roles"]}
        evidence = {"inject": injected, "report": report, "filled": filled, "roles": sorted(roles)}
        write_json(run_directory("fx-tr-reconcile-t0", run_id) / "evidence.json", evidence)
        assert {"interrupted", "replacement_start"} <= roles, evidence
        assert report["points_added"] == 0 and report["frame_ranges_filled"] == 0, evidence


@pytest.mark.asyncio
async def test_fx_tr_cancel_t0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-CANCEL-LIVE's T0 twin (tracing Stage 2, F-S2-9): `cancel --urgency immediate`
    inside S1's running turn; no model call starts after the cancel is accepted and the unit
    settles `cancelled`, not `completed`."""

    from tests.acceptance.mission_control.test_tracing import (
        cancel_immediately,
        settlements_for_run,
        terminal,
    )

    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS", "2.5")
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, TRACING)

        async def s1_running() -> bool:
            return len(stack.model_log) >= 2

        await until(s1_running, seconds=300)
        await cancel_immediately(stack, run_id)
        calls_at_cancel = len(stack.model_log)
        await until(lambda: terminal(stack, run_id), seconds=420)
        settlements = await settlements_for_run(stack, run_id)
        evidence = {
            "calls_at_cancel": calls_at_cancel,
            "calls_after": len(stack.model_log),
            "settlements": settlements,
        }
        write_json(run_directory("fx-tr-cancel-t0", run_id) / "evidence.json", evidence)
        s1 = [item for item in settlements if ":stage:S1:" in item["operation"]]
        assert s1 and s1[-1]["status"] == "cancelled", evidence
        assert len(stack.model_log) <= calls_at_cancel + 1, evidence


@pytest.mark.asyncio
async def test_fx_tr_disconnect_t0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FX-TR-DISCONNECT's T0 twin (tracing Stage 2, F-S2-11): S1's parent call after its first
    tool result fails as a cut provider stream does. The unit settles `failed` once (no
    retry), the run terminates, the settlement records the usage of the calls that completed
    before the failure, and the partial turn has points that hold its frames."""

    from tests.acceptance.mission_control.test_tracing import (
        frames_for_run,
        settlements_for_run,
        terminal,
    )

    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_FAIL_AT_TOOLS", "1")
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, TRACING)
        await until(lambda: terminal(stack, run_id), seconds=300)
        settlements = await settlements_for_run(stack, run_id)
        points = await all_points(stack, run_id)
        frames = await frames_for_run(stack, run_id)
        evidence = {
            "settlements": settlements,
            "points": [(item["roles"], item.get("frames")) for item in points],
            "frame_kinds": sorted({item["kind"] for item in frames}),
            "model_calls": len(stack.model_log),
        }
        write_json(run_directory("fx-tr-disconnect-t0", run_id) / "evidence.json", evidence)
        s1 = [item for item in settlements if ":stage:S1:" in item["operation"]]
        assert len(s1) == 1 and s1[0]["status"] == "failed", evidence
        assert (s1[0]["usage"] or {}).get("tokens.total", 0) > 0, evidence
        assert points and any(item.get("frames") for item in points), evidence


@pytest.mark.asyncio
async def test_failed_producer_behind_a_declared_wait_terminalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-S2-12 (tracing Stage 3, the owner's choice 2026-10-22: terminalize): the two-stage
    blueprint `draft` -> declared wait -> `review` whose draft fails (FX-TR-BUDGET and
    FX-TR-DISCONNECT attempt 1 parked here at the wait). The family skips a wait whose stages
    can never be released and settles the run `failed`, `review` skipped, the wait never set."""

    from tests.acceptance.mission_control.test_tracing import settlements_for_run, terminal
    from tests.fixtures.scoped_api_stack import inspect

    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_FAIL_AT_TOOLS", "1")
    async with scoped_stack(tmp_path, monkeypatch) as stack:
        run_id = await launch(stack, "StageGraph")
        await until(lambda: terminal(stack, run_id), seconds=300)
        state = await inspect(stack, run_id)
        settlements = await settlements_for_run(stack, run_id)
        evidence = {"state": state, "settlements": settlements}
        write_json(run_directory("f-s2-12-t0", run_id) / "evidence.json", evidence)
        # MP-20's concluded failure: the execution ends, its outcome is `failed`.
        assert state["execution_outcome"] == "failed", evidence
        assert state["projection"]["terminal_outcome"] == "failed", evidence
        assert not state["projection"]["active_waits"], evidence
        assert [item["status"] for item in settlements if ":stage:draft:" in item["operation"]] == [
            "failed"
        ], evidence
        assert not [item for item in settlements if ":stage:review:" in item["operation"]], evidence

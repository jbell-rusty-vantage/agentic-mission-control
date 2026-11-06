"""FX-TR-STREAM (tracing Stage 2 §4c): the `/missions` Socket.IO stream beside the transcript.

`mission_socket(application)` mounts the namespace on the scoped stack's already-started
application (`mount_mission_socketio`, exactly as `bootstrap/realtime.py` does) and serves it
on a loopback port with the lifespan off (the stack entered it). `StreamCapture` is one client
subscribed to a run's `mission_events` and `provider_frames` (deltas included, tool detail
`full`), acknowledging what it received so the server's inflight window never fills, and
recording every envelope in arrival order.

`compare(...)` is the fixture's assertion source: the envelopes against the projected
transcript of the same run (`mc.transcript_entry.v2` entries with their `refs.frame_id` /
`refs.event_id` and `point_id`), returning the differences instead of asserting, so the T0 and
the live proofs write them to their evidence before they assert.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from tests.unit.socketio.harness import MissionClient

from mission_control.interfaces.socketio.app import MissionSocketConfig, mount_mission_socketio

DELTA_KINDS = frozenset(
    {"message_delta", "thinking_delta", "tool_call_delta", "heartbeat", "status"}
)
# Written before the turn's first checkpoint, so they carry no `after_point_ref`.
TURN_OPENING_KINDS = frozenset({"session_init", "turn_started", "environment_materialized"})


@asynccontextmanager
async def mission_socket(application: FastAPI) -> AsyncIterator[str]:
    asgi = mount_mission_socketio(
        application, MissionSocketConfig(allowed_origins=("http://127.0.0.1",))
    )
    config = uvicorn.Config(
        asgi, host="127.0.0.1", port=0, lifespan="off", log_level="warning", ws="websockets-sansio"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(15):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=15)


def subscribe_body(run_id: str, cursors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "request_id": f"req-{uuid4()}",
        "application_id": "biotech",
        "target": {"kind": "run", "id": run_id},
        "streams": ["mission_events", "provider_frames"],
        "filters": {"exclude_deltas": False, "tool_detail": "full"},
        "cursors": cursors or [],
        # The sync child's frames are part of the parent's transcript.
        "include_descendants": True,
    }


@dataclass
class StreamCapture:
    url: str
    token: str
    run_id: str
    client: MissionClient = field(default_factory=MissionClient)
    ack: dict[str, Any] = field(default_factory=dict)
    errors: list[Any] = field(default_factory=list)
    _acker: asyncio.Task[None] | None = None

    async def start(self, cursors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        await self.client.connect(self.url, {"application_id": "biotech", "token": self.token})
        self.ack = await self.client.call("subscribe", subscribe_body(self.run_id, cursors))
        if not self.ack.get("ok", False):
            raise AssertionError(f"subscribe refused: {self.ack}")
        self._acker = asyncio.create_task(self._acknowledge())
        return self.ack

    def envelopes(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (name, data)
            for name, data in self.client.order
            if name in {"mission_event", "provider_frame"} and isinstance(data, dict)
        ]

    async def _acknowledge(self) -> None:
        sent: dict[str, str] = {}
        while True:
            await asyncio.sleep(0.5)
            latest: dict[str, dict[str, Any]] = {}
            for _name, data in self.envelopes():
                cursor = data.get("cursor") or {}
                domain = f"{cursor.get('stream')}:{cursor.get('position', '').rpartition(':')[0]}"
                latest[domain] = cursor
            fresh = [
                cursor for key, cursor in latest.items() if sent.get(key) != cursor["position"]
            ]
            if not fresh:
                continue
            try:
                reply = await self.client.call(
                    "ack", {"subscription_id": self.ack["subscription_id"], "cursors": fresh}
                )
            except Exception as error:
                self.errors.append(repr(error))
                continue
            if not reply.get("ok", False):
                self.errors.append(reply)
                continue
            for cursor in fresh:
                key = f"{cursor['stream']}:{cursor['position'].rpartition(':')[0]}"
                sent[key] = cursor["position"]

    async def settle(self, quiet_seconds: float = 3.0, within: float = 120.0) -> None:
        """Wait until no envelope arrived for `quiet_seconds` (the pumps have drained)."""

        async with asyncio.timeout(within):
            count = -1
            while count != len(self.client.order):
                count = len(self.client.order)
                await asyncio.sleep(quiet_seconds)

    async def close(self) -> None:
        if self._acker is not None:
            self._acker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._acker
        await self.client.close()


def compare(
    envelopes: list[tuple[str, dict[str, Any]]], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """The FX-TR-STREAM differences between the stream and the transcript of one run.

    - every frame envelope carries `unit_key` when its transcript entry has one, and its
      `after_point_ref` (the point key the frame followed) when the entry has a point;
    - every unit mission event carries the transcript entry's `unit_key` and `point_ref`;
    - per point, the frames received are the transcript's frames of that point, in order;
    - frames received that the transcript lacks, and the reverse, deltas listed apart.
    """

    by_frame = {
        entry["refs"]["frame_id"]: entry
        for entry in entries
        if entry.get("source") == "provider_frame" and (entry.get("refs") or {}).get("frame_id")
    }
    by_event = {
        entry["refs"]["event_id"]: entry
        for entry in entries
        if entry.get("source") == "mission_event" and (entry.get("refs") or {}).get("event_id")
    }
    frames = [data for name, data in envelopes if name == "provider_frame"]
    events = [data for name, data in envelopes if name == "mission_event"]
    missing_unit = []
    missing_point = []
    before_first_point = []
    for frame in frames:
        entry = by_frame.get(frame["event_id"])
        payload = frame.get("payload") or {}
        if entry is None:
            continue
        if entry.get("unit_key") and payload.get("unit_key") != entry["unit_key"]:
            missing_unit.append((frame["kind"], frame["event_id"]))
        if entry.get("point_id") and not payload.get("after_point_ref"):
            # The frames a turn writes before its first checkpoint follow no point yet
            # (`deep_agents_after_point_ref`); the transcript places them by range.
            if frame["kind"] in TURN_OPENING_KINDS:
                before_first_point.append((frame["kind"], frame["event_id"]))
            else:
                missing_point.append((frame["kind"], frame["event_id"]))
    event_gaps = []
    for event in events:
        entry = by_event.get(event["event_id"])
        payload = event.get("payload") or {}
        if entry is None or not entry.get("unit_key"):
            continue
        if payload.get("unit_key") != entry["unit_key"]:
            event_gaps.append(("unit_key", event["kind"], event["event_id"]))
        if entry.get("point_id") and not payload.get("point_ref"):
            event_gaps.append(("point_ref", event["kind"], event["event_id"]))
    received = [frame["event_id"] for frame in frames]
    received_set = set(received)
    transcript_frames = list(by_frame)
    only_stream = [
        (frame["kind"], frame["event_id"]) for frame in frames if frame["event_id"] not in by_frame
    ]
    only_transcript = [
        (by_frame[frame_id]["kind"], frame_id)
        for frame_id in transcript_frames
        if frame_id not in received_set
    ]
    order_by_point: dict[str, list[str]] = {}
    for frame_id in received:
        entry = by_frame.get(frame_id)
        if entry is not None and entry.get("point_id"):
            order_by_point.setdefault(entry["point_id"], []).append(frame_id)
    expected_by_point: dict[str, list[str]] = {}
    for frame_id, entry in by_frame.items():
        if entry.get("point_id") and frame_id in received_set:
            expected_by_point.setdefault(entry["point_id"], []).append(frame_id)
    misordered = sorted(
        point for point, ids in expected_by_point.items() if order_by_point.get(point) != ids
    )
    return {
        "frames_received": len(frames),
        "events_received": len(events),
        "transcript_frames": len(transcript_frames),
        "frames_without_unit_key": missing_unit,
        "frames_without_after_point_ref": missing_point,
        "frames_before_first_point": before_first_point,
        "unit_events_without_unit_or_point": event_gaps,
        "only_in_stream": [item for item in only_stream if item[0] not in DELTA_KINDS],
        "only_in_stream_deltas": [item for item in only_stream if item[0] in DELTA_KINDS],
        "only_in_transcript": [item for item in only_transcript if item[0] not in DELTA_KINDS],
        "only_in_transcript_deltas": [item for item in only_transcript if item[0] in DELTA_KINDS],
        "points_compared": len(expected_by_point),
        "points_misordered": misordered,
    }


def problems(report: dict[str, Any]) -> list[str]:
    keys = (
        "frames_without_unit_key",
        "frames_without_after_point_ref",
        "unit_events_without_unit_or_point",
        "only_in_stream",
        "only_in_transcript",
        "points_misordered",
    )
    return [key for key in keys if report.get(key)]

"""Full transcripts recover derived frames without weakening byte identity checks."""

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from langchain_core.messages import AIMessage
from scripts.overnight_evidence import export_run, observe_mission_event, recover_mission_event

from mission_control.adapters.deep_agents.frames import message_body
from mission_control.application.frames.transcript import MissionEventRecord, merge
from tests.fixtures.overnight_stagegraph_evidence import recover_tool_call_frame_bodies


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def document(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def observed_frames():
    args = {"items": [{"value": {"summary": "Clinical appraisal — café\n" * 900}}]}
    message = AIMessage(
        id="message-one",
        content="",
        tool_calls=[{"id": "call-one", "name": "submit_output", "args": args}],
    )
    raw = document(message_body(message))
    started = document(
        {
            "tool_call_id": "call-one",
            "name": "submit_output",
            "args": args,
            "args_digest": digest(json.dumps(args, sort_keys=True, separators=(",", ":")).encode()),
            "message_id": "message-one",
        }
    )
    frames = [
        {
            "frame_id": "source",
            "kind": "message",
            "body": raw[:8192].decode(),
            "body_digest": digest(raw),
            "body_bytes": len(raw),
            "body_artifact_ref": "frame-body://source",
            "complete_body": False,
        },
        {
            "frame_id": "target",
            "kind": "tool_call_started",
            "body": started[:8192].decode(),
            "body_digest": digest(started),
            "body_bytes": len(started),
            "body_artifact_ref": None,
            "complete_body": False,
        },
    ]
    return frames, raw, started


@pytest.mark.asyncio
async def test_recovers_full_unicode_tool_frame_and_exports_original_bytes(tmp_path):
    frames, source, original = observed_frames()
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if "/artifacts/" in request.url.path:
            return httpx.Response(200, content=source)
        if request.url.path.endswith("/transcript"):
            return httpx.Response(
                200,
                json={
                    "entries": [
                        {
                            "cursor": "tc1:000000000001:00000000000000000:000000000000:00000000",
                            "run_id": "run",
                            "at": "2026-10-30T00:00:00Z",
                            "source": "provider_frame",
                            "kind": "tool_call_started",
                            "title": "submit_output",
                            "role": "tool",
                            "canonical": False,
                            "body_excerpt": "prefix",
                            "body": {"state": "excerpt", "bytes": len(original)},
                            "refs": {"frame_id": "target"},
                        }
                    ],
                    "has_more": False,
                },
            )
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handle)
    async with httpx.AsyncClient(base_url="http://local/", transport=transport) as client:
        receipts = await recover_tool_call_frame_bodies(frames, client, "run")
    assert frames[1]["body"].encode() == original
    assert frames[1]["complete_body"]
    assert receipts[-1]["source_digest"] == digest(source)
    assert receipts[-1]["digest"] == digest(original)
    assert paths == ["/runs/run/artifacts/frame-body://source"]
    with httpx.Client(base_url="http://local/", transport=transport) as client:
        gaps = export_run(client, "run", tmp_path, observed_frames=frames)
    assert not any("mismatch" in gap or "missing/truncated" in gap for gap in gaps)
    assert (tmp_path / "04-bodies/000000.txt").read_bytes() == original
    proof = json.loads((tmp_path / "06-evidence/body-recovery-000000.json").read_text())
    assert proof["source"] == receipts[-1]["source"]
    assert proof["recovery_provenance"] == receipts[-1]


@pytest.mark.parametrize(
    "change", ["source_bytes", "source_digest", "target_bytes", "target_digest", "args", "http"]
)
@pytest.mark.asyncio
async def test_refuses_unverified_source_or_inexact_reconstruction(change):
    frames, raw, _ = observed_frames()
    excerpt = frames[1]["body"]
    status = 200
    if change == "source_bytes":
        frames[0]["body_bytes"] += 1
    elif change == "source_digest":
        frames[0]["body_digest"] = "sha256:" + "0" * 64
    elif change == "target_bytes":
        frames[1]["body_bytes"] += 1
    elif change == "target_digest":
        frames[1]["body_digest"] = "sha256:" + "0" * 64
    elif change == "args":
        message = json.loads(raw)
        message["tool_calls"][0]["args"] = {"items": []}
        raw = document(message)
        frames[0].update(body_digest=digest(raw), body_bytes=len(raw))
    else:
        status = 404
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=raw))
    async with httpx.AsyncClient(base_url="http://local/", transport=transport) as client:
        await recover_tool_call_frame_bodies(frames, client, "run")
    assert frames[1]["body"] == excerpt
    assert not frames[1]["complete_body"]
    assert "body_recovery" not in frames[1]


@pytest.mark.asyncio
async def test_complete_frames_do_not_trigger_any_read():
    frames, _, original = observed_frames()
    frames[1]["body"] = original.decode()

    def unexpected(request):
        pytest.fail("Complete frames must not trigger artifact reads")

    async with httpx.AsyncClient(
        base_url="http://local/", transport=httpx.MockTransport(unexpected)
    ) as client:
        assert await recover_tool_call_frame_bodies(frames, client, "run") == []


def canonical_event_case(*, wrapped=True):
    """Real production projection, including a distinct native-event reference."""
    payload = {
        "stop_reason": "end_turn",
        "turn_ordinal": 1,
        "usage_refs": [f"provider_frame:00000000-0000-0000-0000-{i:012d}" for i in range(65)],
        "unicode": "Clinical appraisal — café",
        "execution": {"arrival_ordinal": 555},
        "source": {"native_event_ref": "provider_frame:00000000-0000-0000-0000-000000000999"},
        "usage": {"input_tokens": 900},
    }
    record = MissionEventRecord(
        seq=1725,
        event_id="00000000-0000-0000-0000-000000001725",
        event_type="session.turn_completed",
        recorded_at=datetime(2026, 10, 31, tzinfo=UTC),
        actor_ref="fixture",
        payload={"payload": payload, "unit_key": "unit"} if wrapped else payload,
    )
    entry = next(item.entry for item in merge("run", [record], []) if item.entry.canonical)
    observation = observe_mission_event(
        "run",
        {
            "seq": record.seq,
            "event_id": record.event_id,
            "event_type": record.event_type,
            "recorded_at": record.recorded_at,
            "payload": record.payload,
        },
    )
    return entry.model_dump(mode="json"), observation, payload


@pytest.mark.parametrize("wrapped", [True, False])
def test_canonical_recovery_matches_production_projection_and_keeps_envelope(wrapped):
    entry, observation, payload = canonical_event_case(wrapped=wrapped)
    assert entry["body"]["state"] == "excerpt"
    recovered = recover_mission_event("run", entry, [observation])
    assert recovered is not None
    text, proof = recovered
    expected = document(
        {k: v for k, v in payload.items() if k not in {"execution", "source", "usage"}}
    )
    assert text.encode() == expected
    assert entry["body_excerpt"] == text[:2048]
    assert entry["body"]["bytes"] == len(expected)
    assert proof["digest"] == digest(expected)
    assert proof["source"] == "canonical projection of scoped durable mission_event"
    assert proof["durable_event_observation"]["envelope"] == observation["envelope"]
    assert proof["envelope_canonical_digest"] == digest(document(observation["envelope"]))
    assert "not provider bytes" in proof["digest_verification"]


@pytest.mark.parametrize(
    "change",
    [
        "run",
        "entry_run",
        "seq",
        "kind",
        "source",
        "digest",
        "envelope_digest",
        "size",
        "prefix",
        "native_ref",
        "duplicate",
    ],
)
def test_canonical_recovery_refuses_unverified_or_mismatched_event(change):
    entry, observation, _ = canonical_event_case()
    observations = [observation]
    if change == "run":
        observation["run_id"] = "other-run"
    elif change == "seq":
        observation["seq"] += 1
    elif change == "entry_run":
        entry["run_id"] = "other-run"
    elif change == "kind":
        observation["event_type"] = "session.turn_started"
    elif change == "source":
        observation["source"] = "mission_control.provider_frame"
    elif change == "digest":
        observation["body_digest"] = "sha256:" + "0" * 64
    elif change == "envelope_digest":
        observation["envelope_canonical_digest"] = "sha256:" + "0" * 64
    elif change == "size":
        entry["body"]["bytes"] += 1
    elif change == "prefix":
        entry["body_excerpt"] = "different canonical projection"
    elif change == "native_ref":
        entry["refs"]["native_event_ref"] = "provider_frame:00000000-0000-0000-0000-000000000998"
    else:
        observations.append(observation)
    with pytest.raises(ValueError):
        recover_mission_event("run", entry, observations)


def test_wrong_event_id_cannot_supply_canonical_body():
    entry, observation, _ = canonical_event_case()
    observation["event_id"] = "00000000-0000-0000-0000-000000001726"
    assert recover_mission_event("run", entry, [observation]) is None


@pytest.mark.parametrize("supply_event", [True, False])
def test_export_canonical_body_never_substitutes_native_frame(tmp_path, supply_event):
    entry, observation, _ = canonical_event_case()
    native_id = entry["refs"]["native_event_ref"].removeprefix("provider_frame:")
    # Even a misleading frame_id must not route canonical event recovery to a frame.
    entry["refs"]["frame_id"] = native_id
    native_body = document({"stop_reason": "end_turn", "total_tokens": 790621})
    frames = [
        {
            "frame_id": native_id,
            "body": native_body.decode(),
            "body_digest": digest(native_body),
            "body_bytes": len(native_body),
        }
    ]

    def handle(request):
        if request.url.path.endswith("/transcript"):
            return httpx.Response(200, json={"entries": [entry], "has_more": False})
        return httpx.Response(200, json={})

    with httpx.Client(base_url="http://local/", transport=httpx.MockTransport(handle)) as client:
        gaps = export_run(
            client,
            "run",
            tmp_path,
            observed_frames=frames,
            observed_events=[observation] if supply_event else [],
        )
    body = (tmp_path / "04-bodies/000000.txt").read_bytes()
    assert body != native_body
    if supply_event:
        recovered = recover_mission_event("run", entry, [observation])
        assert recovered is not None
        assert body == recovered[0].encode()
        assert not any("missing/truncated" in gap for gap in gaps)
        proof = json.loads((tmp_path / "06-evidence/body-recovery-000000.json").read_text())
        assert proof["event_id"] == entry["refs"]["event_id"]
        assert "frame_id" not in proof
    else:
        assert body == entry["body_excerpt"].encode()
        assert any("missing/truncated" in gap for gap in gaps)
        assert not (tmp_path / "06-evidence/body-recovery-000000.json").exists()

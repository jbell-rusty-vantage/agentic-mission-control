"""Offline controller checks; simulated transport is not live runtime qualification."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.frames.body_refs import frame_body_ref, parse_frame_body_ref
from mission_control.application.knowledge.toolset import LiveInvocation
from tests.fixtures import qualia_scenarios as scenarios
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.fixtures.qualia_interventions import Interventions
from tests.fixtures.qualia_scenarios import _applied, controller


@pytest.mark.asyncio
async def test_transcript_pagination_stops_at_resumable_tail_watermark() -> None:
    observed = []

    def response(request: httpx.Request) -> httpx.Response:
        observed.append(request.url.params.get("since"))
        if len(observed) == 1:
            return httpx.Response(
                200, json={"entries": [{"id": 1}], "next_cursor": "c1", "has_more": True}
            )
        return httpx.Response(
            200, json={"entries": [{"id": 2}], "next_cursor": "c2", "has_more": False}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="http://local"
    ) as http:
        rows = await scenarios._entries(http, "/transcript", cursor_parameter="since")
    assert rows == [{"id": 1}, {"id": 2}]
    assert observed == [None, "c1"]


@pytest.mark.asyncio
async def test_transcript_empty_tail_keeps_resume_cursor_without_looping() -> None:
    requests = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"entries": [], "next_cursor": "tail", "has_more": False})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="http://local"
    ) as http:
        assert await scenarios._entries(http, "/transcript", since="tail") == []
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_pagination_still_refuses_repeated_cursor_with_more_results() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"entries": [{"id": 1}], "next_cursor": "same", "has_more": True}
            )
        ),
        base_url="http://local",
    ) as http:
        with pytest.raises(AssertionError, match="repeated its cursor"):
            await scenarios._entries(http, "/transcript", cursor_parameter="since")


def _capture_request(
    node: str,
    text: str,
    blobs: dict[str, bytes],
    *,
    promoted_frame: bool = False,
) -> dict[str, Any]:
    def descriptor(value: Any) -> dict[str, Any]:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        blobs[digest] = raw
        return {
            "ref": frame_body_ref(
                digest=digest, size_bytes=len(raw), media_type="application/json"
            ),
            "digest": digest,
            "bytes": len(raw),
            "type": "human",
        }

    message = descriptor({"type": "human", "content": text})
    frame = descriptor({"messages": [message], "system": None})
    return {
        "node_key": node,
        "kind": "model_request",
        "body_excerpt": "{}" if promoted_frame else blobs[frame["digest"]].decode(),
        "body": {
            "bytes": frame["bytes"],
            **({"artifact_ref": frame["ref"]} if promoted_frame else {}),
        },
        "refs": {
            "body_digest": frame["digest"],
            **({"artifact_ref": frame["ref"]} if promoted_frame else {}),
        },
    }


def _artifact_response(path: str, blobs: dict[str, bytes]) -> httpx.Response:
    ref = unquote(path.split("/artifacts/", 1)[1])
    return httpx.Response(200, content=blobs[parse_frame_body_ref(ref).digest])


def test_acceptance_alone_is_not_applied_delivery_and_failed_controls_refuse() -> None:
    def status(state: str) -> dict[str, Any]:
        return {"commands": [{"command": {"command_id": "c1"}, "receipts": [{"state": state}]}]}

    assert not _applied(status("accepted"), "c1", injected=False)
    assert not _applied(status("applied"), "c1", injected=False)
    for terminal in ("failed", "expired", "rejected"):
        with pytest.raises(AssertionError, match=terminal):
            _applied(status(terminal), "c1", injected=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered", [False, True])
async def test_promoted_request_and_message_bodies_require_verified_scoped_bytes(
    tampered: bool,
) -> None:
    blobs: dict[str, bytes] = {}
    entry = _capture_request("studies", "ACTUAL-MODEL-MARKER", blobs, promoted_frame=True)
    if tampered:
        message_digest = json.loads(blobs[entry["refs"]["body_digest"]])["messages"][0]["digest"]
        blobs[message_digest] += b" "
    paths = []

    def response(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return _artifact_response(request.url.path, blobs)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="http://local"
    ) as http:
        call = scenarios._model_messages(http, "/v1/applications/biotech/runs/derived", [entry], {})
        if tampered:
            with pytest.raises(AssertionError, match="digest/byte count mismatch"):
                await call
        else:
            proof = await call
            assert proof[0]["frame_read"]["verified"]
            assert proof[0]["messages"][0]["verified"]
            assert "ACTUAL-MODEL-MARKER" in json.dumps(proof[0]["messages"][0]["body"])
    assert len(paths) == 2
    assert all(
        path.startswith("/v1/applications/biotech/runs/derived/artifacts/") for path in paths
    )


@pytest.mark.asyncio
async def test_metadata_marker_is_not_a_model_visible_message() -> None:
    blobs: dict[str, bytes] = {}
    entry = _capture_request("studies", "Ordinary input without the directive", blobs)
    metadata = json.loads(entry["body_excerpt"])
    metadata["not_a_message"] = "METADATA-ONLY-MARKER"
    entry["body_excerpt"] = json.dumps(metadata)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: _artifact_response(request.url.path, blobs)),
        base_url="http://local",
    ) as http:
        proof = await scenarios._model_messages(http, "/runs/derived", [entry], {})
    assert all(
        "METADATA-ONLY-MARKER" not in json.dumps(message["body"])
        for row in proof
        for message in row["messages"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_tool", [True, False])
async def test_controller_uses_actual_checkpoint_context_and_demands_cancellation(
    tmp_path: Path,
    cancel_tool: bool,
) -> None:
    interventions = Interventions()
    posted: dict[str, Any] = {}
    blobs: dict[str, bytes] = {}

    async def checkpoint(position: str) -> str:
        live = LiveInvocation(
            "scope", "source", f"operation-{position}", 1, 1, "deep_agents", position=position
        )
        token = CURRENT_INVOCATION.set(live)
        try:
            return await interventions.checkpoint()
        finally:
            CURRENT_INVOCATION.reset(token)

    tasks = {
        position: asyncio.create_task(checkpoint(position))
        for position in ("formulations", "studies")
    }

    def response(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/artifacts/" in path:
            return _artifact_response(path, blobs)
        if request.method == "POST":
            body = json.loads(request.content)
            position = body["payload"]["node_key"]
            posted[position] = body
            if position == "studies" and cancel_tool:
                tasks[position].cancel()
            return httpx.Response(
                202,
                json={
                    "admission": {
                        "status": "accepted",
                        "command_id": body["request_id"],
                    }
                },
            )
        if path.endswith("/inspection"):
            return httpx.Response(
                200, json={"version": 1, "execution_generation": 1, "phase": "running"}
            )
        if path.endswith("/commands"):
            commands = []
            for position, body in posted.items():
                report: dict[str, Any] = {
                    "observed_outcome": "delivered",
                    "delivered_semantics": "next_turn",
                }
                if position == "studies":
                    report.update(
                        delivered_semantics="cancel_and_replace",
                        native_refs={
                            "cancelled_turn_ref": "old-turn",
                            "replacement_turn_ref": "new-turn",
                        },
                    )
                commands.append(
                    {
                        "command": {"command_id": body["request_id"]},
                        "receipts": [{"state": "applied", "delivery_report": report}],
                    }
                )
            return httpx.Response(200, json={"commands": commands})
        if path.endswith("/transcript"):
            return httpx.Response(
                200,
                json={
                    "entries": [
                        _capture_request(position, body["payload"]["content"]["text"], blobs)
                        for position, body in posted.items()
                    ]
                },
            )
        raise AssertionError(path)

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(response), base_url="http://controls"
        ) as http:
            call = controller(
                SimpleNamespace(database=SimpleNamespace(application_id="biotech")),
                http,
                "source",
                interventions,
                tmp_path,
                timeout_seconds=2 if cancel_tool else 0.1,
            )
            if cancel_tool:
                result = await call
                assert result["result"] == "passed"
                assert all(result["model_visible_markers"].values())
            else:
                with pytest.raises(TimeoutError):
                    await call
        assert interventions.released == {"formulations", "studies"}
        proof = json.loads((tmp_path / "live-controls.json").read_text())
        assert proof["result"] == ("passed" if cancel_tool else "failed")
        assert any(
            row["event"] == "model_requested_checkpoint" for row in proof["checkpoint_events"]
        )
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_checkpoint_refuses_a_fabricated_or_absent_invocation() -> None:
    token = CURRENT_INVOCATION.set(None)
    try:
        with pytest.raises(ValueError, match="actual admitted invocation"):
            await Interventions().checkpoint()
    finally:
        CURRENT_INVOCATION.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared_executes", [False, True])
async def test_fork_selects_a_settled_root_cursor_and_launches_prepared_erc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepared_executes: bool,
) -> None:
    def point(name: str, ordinal: int) -> dict[str, Any]:
        return {
            "point_id": name,
            "ordinal": ordinal,
            "seedable": True,
            "location": {"family": "stage_graph", "node_key": "studies", "cycle": 0},
            "coordinate": {
                "run_id": "source",
                "unit_key": "source-unit",
                "point": {"kind": "checkpoint", "key": {"checkpoint_id": name}},
            },
        }

    safe, pending = point("safe-result", 1), point("pending-tools", 2)
    observed: dict[str, Any] = {"launched": False}
    blobs: dict[str, bytes] = {}

    def response(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/artifacts/" in path:
            return _artifact_response(path, blobs)
        if path.endswith("/source/inspection"):
            body = {"phase": "terminal", "execution_outcome": "completed", "version": 3}
        elif path.endswith("/source/points"):
            body = {"entries": [safe, pending]}
        elif path.endswith("/state-as-of"):
            body = {
                "state": {
                    "pending_tasks": ["tools"] if "pending-tools" in path else [],
                    "interrupts": [],
                }
            }
        elif path.endswith("/source/snapshots"):
            body = {
                "snapshot": {
                    "source_run_id": "source",
                    "snapshot_id": "run-snapshot:source",
                    "snapshot_digest": "sha256:" + "a" * 64,
                    "effective_configuration_digest": "sha256:" + "b" * 64,
                }
            }
        elif path.endswith("/prepared/inspection"):
            executing = prepared_executes and observed["launched"]
            body = {
                "phase": "running" if executing else "pending",
                "version": 1,
                "projection": {
                    "input_manifest": {"digest": "sha256:" + "d" * 64},
                    "execution_target": {"workflow_id": "unexpected"} if executing else None,
                    "effective_configuration_digest": "sha256:" + "c" * 64,
                },
            }
        elif path.endswith("/prepared/points"):
            body = {"entries": []}
        elif path.endswith("/source/forks"):
            observed["fork"] = json.loads(request.content)
            body = {
                "receipt": {
                    "request_id": "scoped-fork",
                    "target_run_id": "derived",
                    "reused_units": [],
                    "start_position": None,
                }
            }
        elif path.endswith("/derived/inspection"):
            body = {
                "phase": "terminal" if observed["launched"] else "pending",
                "version": 1,
                "execution_outcome": "completed" if observed["launched"] else None,
            }
        elif path.endswith("/derived/launch"):
            observed.update(launched=True, launch=json.loads(request.content))
            body = {"run_id": "derived"}
        elif path.endswith("/derived/points"):
            body = {"entries": [{"parent_coordinate": safe["coordinate"]}]}
        elif path.endswith("/derived/transcript"):
            if request.url.params["kinds"] == "model_request":
                body = {
                    "entries": [
                        _capture_request(
                            "studies",
                            observed["fork"]["message"]["text"],
                            blobs,
                            promoted_frame=True,
                        )
                    ]
                }
            else:
                body = {
                    "entries": [
                        {
                            "body_excerpt": json.dumps(
                                {
                                    "skills": [{"name": "qualia-tavily-research"}],
                                    "files": [{"path": "/skills/qualia-tavily-research/SKILL.md"}],
                                }
                            )
                        }
                    ]
                }
        else:
            raise AssertionError(path)
        return httpx.Response(202 if request.method == "POST" else 200, json=body)

    class Author:
        async def family_input(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["run_id"] == "prepared"
            return {
                "run_id": "prepared",
                "effective_configuration_digest": "sha256:" + "c" * 64,
                "semantic_input_binding_ref": "semantic-input:manifest:prepared",
            }

    class Lifecycle:
        _launch_inputs = Author()

        async def submit(self, request: Any) -> Any:
            assert request.manifest_yaml == "prepared Tavily manifest"
            return SimpleNamespace(
                missions=[SimpleNamespace(family="StageGraph", run_id="prepared")]
            ), False

    class Root:
        async def describe(self) -> Any:
            return SimpleNamespace(workflow_type="mc.mission_run.v1")

        async def result(self) -> Any:
            return {"durable": True}

    async def materialization(*args: Any) -> list[dict[str, Any]]:
        return [{"fixture": "saved-binding-double"}]

    monkeypatch.setattr(scenarios, "_fork_materialization", materialization)
    stack = SimpleNamespace(
        database=SimpleNamespace(application_id="biotech", scope=lambda _name: canonical_scope()),
        client=SimpleNamespace(get_workflow_handle=lambda _id: Root()),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), base_url="http://local"
    ) as http:
        call = scenarios.fork_from_completed_stage(
            stack,
            http,
            "source",
            Lifecycle(),
            "prepared Tavily manifest",
            tmp_path,
        )
        if prepared_executes:
            with pytest.raises(AssertionError, match="prepared template run started"):
                await call
            failed = json.loads((tmp_path / "fork-scenario.json").read_text())
            assert failed["result"] == "failed"
            assert failed["prepared_run_after_fork"]["phase"] == "running"
            return
        result = await call
    assert result["result"] == "passed" and result["seed_point"] == safe
    assert result["prepared_run_before_fork"] == result["prepared_run_after_fork"]
    assert result["prepared_run_points"] == []
    assert observed["fork"]["cognitive_seed"]["checkpoint"]["checkpoint_id"] == "safe-result"
    assert (
        observed["launch"]["source_semantic_input_binding_ref"]
        == "semantic-input:manifest:prepared"
    )
    assert (
        observed["launch"]["stagegraph"]["semantic_input_binding_ref"]
        == "semantic-input:fork:scoped-fork"
    )

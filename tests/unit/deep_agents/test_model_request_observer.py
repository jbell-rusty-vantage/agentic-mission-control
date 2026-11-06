"""The model-input record (1.4.4, P3.4, TR-G1): a real `create_deep_agent` run through the
adapter with a scripted three-call model, the in-memory saver, the in-memory FrameStore and a
recording promoter composed as the `FrameCapture`.

Offline: no provider is contacted. Proves the `_ModelRequestObserver` at the chat-model
boundary: one `model_request` frame per call keyed by the step, each ordered before the
`message` frame of its response, message digests equal to the `message` and tool-result
frames' body digests, human and system messages promoted once per digest, and the batch
digest equal to a reconstruction from those parts (P4.3 replay).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid5

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from mission_control.adapters.deep_agents import DeepAgentRuntimeAdapter, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.frames import model_request_capture
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.application.frames.capture_policy import (
    FULL_REQUESTS_PROFILE,
    STANDARD_PROFILE,
    FrameCapture,
)
from mission_control.domain.frames.body import canonical_bytes
from mission_control.domain.frames.contracts import FrameKind, HarnessExecutionHandle
from tests.acceptance.control_plane.test_wp_cp_040 import registry
from tests.fixtures.provider_frames import INSTALLATION, SCOPE
from tests.unit.frames.test_deep_agents_frames import _planned, _store_for, _unit_binding

SKILL_MD = "/skills/exact-binding-proof/SKILL.md"


class ThreeCallModel(BaseChatModel):
    """Call 1 reads the Skill, call 2 lists the Skill root, call 3 answers."""

    calls: int = 0
    seen_batches: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "three-call-scripted"

    def bind_tools(
        self,
        tools: Sequence[BaseTool | dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.calls += 1
        self.seen_batches.append(list(messages))
        tools = [item for item in messages if isinstance(item, ToolMessage)]
        usage = {
            "input_tokens": 5 * self.calls,
            "output_tokens": 2,
            "total_tokens": 5 * self.calls + 2,
        }
        if len(tools) == 0:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": SKILL_MD, "limit": 1000},
                        "id": "req-read-1",
                        "type": "tool_call",
                    }
                ],
                usage_metadata=usage,
            )
        elif len(tools) == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "ls",
                        "args": {"path": "/skills/exact-binding-proof"},
                        "id": "req-ls-2",
                        "type": "tool_call",
                    }
                ],
                usage_metadata=usage,
            )
        else:
            message = AIMessage(content="Three calls observed.", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


class RecordingPromoter:
    """A `FrameBodyPromoter` that keeps every promoted object by digest."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.keys: list[tuple[str, str]] = []

    async def promote_frame_body(
        self,
        handle: HarnessExecutionHandle,
        *,
        promotion_key: str,
        kind: FrameKind,
        digest: str,
        media_type: str,
        payload: bytes,
    ) -> str:
        del handle
        self.objects[digest] = payload
        self.keys.append((kind.value, promotion_key))
        return f"frame-body://{digest}?bytes={len(payload)}&type={media_type}"


def _step_of(key: str, thread: str) -> int:
    # `thread::<checkpoint>:<step>:call:<n>:model_request`
    rest = key[len(thread) + 2 :]
    _checkpoint, step, _tail = rest.split(":", 2)
    return int(step)


async def _run(capture: FrameCapture) -> tuple[Any, Any, Any, ThreeCallModel, RecordingPromoter]:
    binding, bundle, unit = _unit_binding()
    store = _store_for(unit)
    model = ThreeCallModel()
    adapter = DeepAgentRuntimeAdapter(
        ExactDeepAgentMaterializer(registry(binding, bundle, model)),
        frames=store,
        frame_capture=capture,
    )
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    invocation = await _planned(binding, lineage)
    result = await adapter.execute(
        invocation, {"environment:FIXTURE_TOKEN": "fixture-secret-value"}
    )
    assert result.output_text == "Three calls observed."
    frames = await store.frames_for_run(SCOPE, uuid5(INSTALLATION, unit.belllabs_run_id))
    promoter = capture.promoter
    assert isinstance(promoter, RecordingPromoter)
    return binding, store, frames, model, promoter


@pytest.mark.asyncio
async def test_three_model_calls_leave_three_model_request_frames_before_their_responses() -> None:
    promoter = RecordingPromoter()
    binding, store, frames, model, promoter = await _run(
        FrameCapture(policy=STANDARD_PROFILE, promoter=promoter)
    )
    thread = binding.cognitive_session_namespace
    requests = [frame for frame in frames if frame.kind == FrameKind.MODEL_REQUEST]
    responses = [frame for frame in frames if frame.kind == FrameKind.MESSAGE]
    assert model.calls == len(requests) == len(responses) == 3
    # Each request precedes the response of its call and follows the previous response.
    for index, (request, response) in enumerate(zip(requests, responses, strict=True)):
        assert request.arrival_ordinal < response.arrival_ordinal
        if index:
            assert request.arrival_ordinal > responses[index - 1].arrival_ordinal
        assert request.raw_kind == "model.request" and not request.closing
        assert request.native_turn_ref == response.native_turn_ref
    # The step keys: one call per step, the first within the step, strictly increasing steps.
    steps = [_step_of(frame.provider_key, thread) for frame in requests]
    assert steps == sorted(steps) and len(set(steps)) == 3
    assert all(frame.provider_key.endswith(":call:1:model_request") for frame in requests)
    bodies = [json.loads(frame.body_excerpt) for frame in requests]
    assert [body["call_index"] for body in bodies] == [1, 1, 1]
    assert [body["langgraph"]["step"] for body in bodies] == steps
    assert all(body["langgraph"]["node"] == "model" for body in bodies)
    assert all(body["follow_up"] is False for body in bodies)
    assert all(body["model"]["invocation_params_digest"].startswith("sha256:") for body in bodies)
    # `ls_provider` of a model without an override: the class name, lowercased
    # (langchain_core `_get_ls_params` fallback); real providers set it themselves.
    assert bodies[0]["model"]["provider"] == "threecallmodel"
    assert (
        bodies[0]["tool_choice"] is None and bodies[0]["tools"] == []
    )  # the fixture binds no tools
    # The system prompt is the first message of every batch: promoted once by digest.
    system_digests = {body["system"]["digest"] for body in bodies}
    assert len(system_digests) == 1
    (system_digest,) = system_digests
    assert all(
        body["system"]["ref"].startswith(f"frame-body://{system_digest}?") for body in bodies
    )
    assert (
        promoter.keys.count(
            ("model_request", f"{requests[0].harness_execution_id}:1:msg:{system_digest}")
        )
        == 1
    )
    assert "fixture-secret-value" not in "".join(frame.body_excerpt for frame in frames)
    # Message entries: human messages are promoted objects; AI and tool messages are the
    # digests of their `message` and tool-result frames (same body, same redaction).
    by_digest = {frame.body_digest: frame for frame in frames}
    final = bodies[-1]
    types = [entry["type"] for entry in final["messages"]]
    assert types == ["human", "ai", "tool", "ai", "tool"]
    for entry in final["messages"]:
        if entry["type"] == "human":
            assert entry["ref"].startswith(f"frame-body://{entry['digest']}?")
            assert entry["digest"] in promoter.objects
        else:
            frame = by_digest[entry["digest"]]
            assert frame.kind in {FrameKind.MESSAGE, FrameKind.TOOL_CALL_COMPLETED}
            assert "ref" not in entry
            assert entry["id"] == json.loads(frame.body_excerpt)["id"]
    # P4.3: the batch digest is a reconstruction from the parts alone.
    parts: list[Any] = [json.loads(promoter.objects[system_digest])]
    for entry in final["messages"]:
        payload = promoter.objects.get(entry["digest"])
        if payload is None:
            frame = by_digest[entry["digest"]]
            assert len(frame.body_excerpt.encode("utf-8")) == frame.body_bytes
            payload = frame.body_excerpt.encode("utf-8")
        parts.append(json.loads(payload))
    assert final["batch_digest"] == "sha256:" + hashlib.sha256(canonical_bytes(parts)).hexdigest()
    assert "batch_ref" not in final  # `standard` keeps the per-message objects only
    assert final["batch_bytes"] == len(canonical_bytes(parts))
    # The profile name travels on the harness execution.
    execution = store._executions[requests[0].harness_execution_id]
    assert execution.start is not None
    assert execution.start.native_identity["frame_capture_profile"] == "standard"
    # The request batch the observer recorded is the batch the model received.
    assert len(model.seen_batches[-1]) == 1 + len(final["messages"])


@pytest.mark.asyncio
async def test_full_requests_profile_promotes_the_whole_batch_of_every_call() -> None:
    promoter = RecordingPromoter()
    _binding, _store, frames, _model, promoter = await _run(
        FrameCapture(policy=FULL_REQUESTS_PROFILE, promoter=promoter)
    )
    requests = [frame for frame in frames if frame.kind == FrameKind.MODEL_REQUEST]
    bodies = [json.loads(frame.body_excerpt) for frame in requests]
    for body in bodies:
        assert body["batch_ref"].startswith(f"frame-body://{body['batch_digest']}?")
        assert promoter.objects[body["batch_digest"]] == canonical_bytes(
            json.loads(promoter.objects[body["batch_digest"]])
        )
        assert len(promoter.objects[body["batch_digest"]]) == body["batch_bytes"]
    assert len({body["batch_digest"] for body in bodies}) == 3


def test_model_request_capture_lists_bound_tools_and_the_tool_choice() -> None:
    from langchain_core.messages import HumanMessage, SystemMessage

    capture = model_request_capture(
        [SystemMessage("rules"), HumanMessage("go", id="h-1")],
        ns=("tools:t-1",),
        step=3,
        node="model",
        checkpoint_ns="tools:t-1|model:m-2",
        invocation_params={
            "_type": "openai-chat",
            "model_name": "gpt-x",
            "tools": [
                {"type": "function", "function": {"name": "read_file", "parameters": {}}},
                {"name": "ls", "input_schema": {}},
            ],
            "tool_choice": "auto",
            "stop": None,
        },
        metadata={"ls_provider": "openai", "ls_model_name": "gpt-x"},
        call_index=2,
        follow_up=True,
        full_requests=True,
    )
    body = capture.body
    assert body["model"] == {
        "name": "gpt-x",
        "provider": "openai",
        "invocation_params_digest": body["model"]["invocation_params_digest"],
    }
    assert [tool["name"] for tool in body["tools"]] == ["read_file", "ls"]
    assert all(tool["schema_digest"].startswith("sha256:") for tool in body["tools"])
    assert body["tool_choice"] == "auto" and body["follow_up"] is True
    assert body["langgraph"] == {"step": 3, "node": "model", "checkpoint_ns": "tools:t-1|model:m-2"}
    assert body["system"] == {"digest": body["system"]["digest"], "bytes": body["system"]["bytes"]}
    assert [entry["type"] for entry in body["messages"]] == ["human"]
    assert set(capture.objects) == {body["system"]["digest"], body["messages"][0]["digest"]}
    assert capture.batch is not None and capture.batch[0] == body["batch_digest"]
    assert capture.ns == ("tools:t-1",) and capture.call_index == 2

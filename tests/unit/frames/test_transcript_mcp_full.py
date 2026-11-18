"""`mission_run_transcript(full=true)`: an MCP-only Coordinator reads what the model received.

A `model_request` entry names its system prompt and messages by `frame-body://` reference.
The HTTP route's `full=true` reads them through the tenant's artifact body reader; the MCP
tool now does the same, so a Coordinator without a filesystem can read a node's Purpose Card
back. Without a reader composed the tool refuses instead of answering without the bodies.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.application.frames.transcript import TranscriptDenied, TranscriptService
from mission_control.domain.execution.contracts import PURPOSE_CARD_HEADER
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from mission_control.interfaces.mcp.transcript_tools import (
    TRANSCRIPT_TOOL,
    ScopedTranscripts,
    register_transcript_tools,
)
from tests.fixtures.provider_frames import provider_frame
from tests.fixtures.transcripts import RUN_KEY, InMemoryMissionEvents, StaticFrames
from tests.support.ids import SCOPE

CARD = f"{PURPOSE_CARD_HEADER}\n\nWhy the mission exists and what this node's part is."


def ref(name: str) -> str:
    digest = "sha256:" + sha256(name.encode()).hexdigest()
    return frame_body_ref(digest=digest, size_bytes=10, media_type="application/json")


SYSTEM, HUMAN = ref("system"), ref("human")
BODIES = {
    SYSTEM: {"type": "system", "content": [{"type": "text", "text": f"{CARD}\n\nHost line."}]},
    HUMAN: {"type": "human", "content": "Mission hello stage write: write the text."},
}


class Bodies:
    """The tenant's artifact body reader: it needs the artifact read grant."""

    def __init__(self) -> None:
        self.reads: list[str] = []

    async def read(self, request_scope: str, actor: ActorContext, artifact_ref: str) -> str:
        assert request_scope == SCOPE
        if "workflow.result.read" not in actor.permissions:
            raise PermissionError("artifact read grant missing")
        self.reads.append(artifact_ref)
        return json.dumps(BODIES[artifact_ref])


def service() -> TranscriptService:
    request = provider_frame(
        1, FrameKind.MODEL_REQUEST, {"system": {"ref": SYSTEM}, "messages": [{"ref": HUMAN}]}
    )
    return TranscriptService(
        InMemoryMissionEvents([]),
        StaticFrames([request]),  # type: ignore[arg-type]
        request_scope=SCOPE,
    )


def server(transcripts: ScopedTranscripts, permissions: frozenset[str]) -> FastMCP:
    principal = CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=permissions,
        request_scope=SCOPE,
    )

    class Principals:
        async def resolve(self, context: Any) -> CoordinatorPrincipal:
            del context
            return principal

    mcp = FastMCP("transcript-full-test")
    register_transcript_tools(mcp, transcripts, Principals(), call=_principal_call)
    return mcp


async def read(mcp: FastMCP, **arguments: Any) -> dict[str, Any]:
    async with Client(mcp) as client:
        result = await client.call_tool(
            TRANSCRIPT_TOOL,
            {"run_id": RUN_KEY, "kinds": ["model_request"], "limit": 1, **arguments},
            raise_on_error=False,
        )
    envelope = result.structured_content
    assert envelope is not None
    return dict(envelope)


@pytest.mark.asyncio
async def test_full_inlines_the_system_prompt_and_the_messages_of_a_model_request() -> None:
    bodies = Bodies()
    mcp = server(
        ScopedTranscripts({SCOPE: service()}, artifacts={SCOPE: bodies}),
        frozenset({"workflow.result.read"}),
    )

    plain = await read(mcp)
    full = await read(mcp, full=True)

    # Without `full` the entry names the bodies by reference alone, and nothing is read.
    (entry,) = plain["data"]["entries"]
    assert json.loads(entry["body_excerpt"]) == {
        "messages": [{"ref": HUMAN}],
        "system": {"ref": SYSTEM},
    }
    # With it, each reference carries the body the model received: the card opens the prompt.
    (entry,) = full["data"]["entries"]
    request = json.loads(entry["body_excerpt"])
    assert request["system"]["ref"] == SYSTEM
    assert request["system"]["body"]["content"][0]["text"].startswith(CARD)
    assert request["messages"][0]["body"] == BODIES[HUMAN]
    assert bodies.reads == [SYSTEM, HUMAN]
    async with Client(mcp) as client:
        tool = {item.name: item for item in await client.list_tools()}[TRANSCRIPT_TOOL]
    argument = tool.inputSchema["properties"]["full"]
    assert argument["type"] == "boolean" and argument["default"] is False
    assert "`full` inlines referenced bodies" in (tool.description or "")


@pytest.mark.asyncio
async def test_full_is_refused_without_a_reader_or_without_the_artifact_grant() -> None:
    unwired = server(ScopedTranscripts({SCOPE: service()}), frozenset({"workflow.result.read"}))
    ungranted = server(
        ScopedTranscripts({SCOPE: service()}, artifacts={SCOPE: Bodies()}),
        frozenset({"mission.read"}),
    )

    no_reader = await read(unwired, full=True)
    denied = await read(ungranted, full=True)

    assert no_reader["ok"] is False
    assert no_reader["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "full bodies need the artifact read API" in no_reader["error"]["message"]
    assert denied["ok"] is False and denied["error"]["code"] == "FORBIDDEN"
    # The same principal still reads the transcript without the bodies.
    assert (await read(ungranted))["ok"] is True
    # The service itself refuses the read: the tool maps that refusal, it does not widen it.
    with pytest.raises(TranscriptDenied):
        await (
            service()
            .with_artifacts(Bodies())
            .materialize(
                RUN_KEY,
                actor=ActorContext(actor_id="reader", permissions=frozenset({"workflow_run.read"})),
                full=True,
            )
        )

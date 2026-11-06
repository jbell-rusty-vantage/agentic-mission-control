"""FT-A5 in a real compiled Deep Agents graph with a scripted (offline) chat model."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.hooks import (
    HookContext,
    HookDispatcher,
    HookScriptMiddleware,
    KernelHookPorts,
    MissionSummarizationMiddleware,
    RecordingFrameSink,
    ResolvedHookScript,
    StreamFrameSink,
    StreamUsageRecorder,
    SubprocessHookScriptRunner,
)
from mission_control.contracts.hooks import HookScope
from mission_control.domain.capabilities.hooks import KERNEL_HOOK_IDS, HookEvent

POLICY = Path(__file__).resolve().parents[3] / "scripts" / "hooks" / "policy_template" / "policy.py"
EXECUTED: list[str] = []


@tool
def shell(command: str) -> str:
    """Run a shell command (fixture: records instead of executing)."""
    EXECUTED.append(command)
    return f"ran {command}"


class ScriptedModel(BaseChatModel):
    """First turn calls ``shell``; second turn answers. No provider is contacted."""

    command: str = "rm -rf /"

    @property
    def _llm_type(self) -> str:
        return "scripted-hook-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        if any(isinstance(message, ToolMessage) for message in messages):
            reply = AIMessage(id="msg-2", content="finished", usage_metadata=usage)
        else:
            reply = AIMessage(
                id="msg-1",
                content="",
                tool_calls=[{"name": "shell", "args": {"command": self.command}, "id": "call-1"}],
                usage_metadata=usage,
            )
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _agent(model: ScriptedModel, ports: KernelHookPorts, tmp_path: Path) -> Any:
    dispatcher = HookDispatcher(
        context=HookContext(scope=HookScope(installation_id="i", application_id="biotech")),
        kernel_hooks=ports.build(),
        scripts=(
            ResolvedHookScript(
                hook_id="hook.mc-policy-template",
                events=frozenset({HookEvent.BEFORE_SHELL, HookEvent.BEFORE_TOOL}),
                interpreter="python",
                entrypoint=POLICY,
                fail_closed=True,
            ),
        ),
        runner=SubprocessHookScriptRunner(),
        frames=ports.frames,
        cwd=tmp_path,
    )
    backend = StateBackend()
    return create_deep_agent(
        model=model,
        tools=[shell],
        middleware=[
            HookScriptMiddleware(dispatcher),
            MissionSummarizationMiddleware.from_default(model, backend, dispatcher),
        ],
        backend=backend,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "executed"), [("rm -rf /", False), ("pytest -q", True)])
async def test_policy_hook_governs_the_shell_tool_in_a_compiled_graph(
    command: str, executed: bool, tmp_path: Path
) -> None:
    EXECUTED.clear()
    frames = RecordingFrameSink()
    agent = _agent(ScriptedModel(command=command), KernelHookPorts(frames=frames), tmp_path)
    result = await agent.ainvoke({"messages": [HumanMessage(content="clean up")]})
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert ([command] == EXECUTED) is executed
    assert len(tool_messages) == 1
    if not executed:
        assert tool_messages[0].status == "error"
        assert "Denied by Mission Control hook" in str(tool_messages[0].content)
    events = {(frame.hook_id, frame.event.value) for frame in frames.frames}
    assert ("mc.stop_fence", "before_shell") in events
    assert ("hook.mc-policy-template", "before_shell") in events
    assert ("mc.frame_capture", "session_start") in events
    assert ("mc.usage", "stop") in events


@pytest.mark.asyncio
async def test_stream_ports_emit_hook_and_usage_events_through_the_graph_stream(
    tmp_path: Path,
) -> None:
    """P3.5: the production frame sink and usage port reach the graph's `custom` stream
    (what the Deep Agents frame recorder consumes), kernel hooks first and in kernel order."""

    EXECUTED.clear()
    sink = StreamFrameSink()
    usage = StreamUsageRecorder()
    agent = _agent(
        ScriptedModel(command="pytest -q"), KernelHookPorts(frames=sink, usage=usage), tmp_path
    )
    customs: list[dict[str, Any]] = []
    async for mode, chunk in agent.astream(
        {"messages": [HumanMessage(content="clean up")]}, stream_mode=["custom", "updates"]
    ):
        if mode == "custom":
            customs.append(dict(chunk))
    assert EXECUTED == ["pytest -q"]
    assert sink.dropped == 0 and usage.dropped == 0 and sink.emitted > 0
    invoked = [event for event in customs if event["type"] == "mc.hook_invoked"]
    results = [event for event in customs if event["type"] == "mc.hook_result"]
    assert len(invoked) == len(results) == sink.emitted
    shell_hooks = [event["hook_id"] for event in invoked if event["event"] == "before_shell"]
    assert shell_hooks == [*KERNEL_HOOK_IDS[:3], "hook.mc-policy-template"]
    assert [event["tool_call_id"] for event in invoked if event["event"] == "before_shell"] == [
        "call-1"
    ] * 4
    assert len({event["id"] for event in customs if event["type"] != "mc.usage"}) == len(
        invoked
    ) + len(results)
    # One usage event per model answer, with the counts the model reported.
    usages = [event for event in customs if event["type"] == "mc.usage"]
    assert [event["message_id"] for event in usages] == ["msg-1", "msg-2"]
    assert all(
        (event["input_tokens"], event["output_tokens"], event["total_tokens"]) == (3, 2, 5)
        for event in usages
    )
    assert usage.emitted == 2

"""Tracing proposal P3.5 (TR-D4): the Deep Agents lane's production kernel hook ports.

The four ports the deployment composition wires (`compose_kernel_hook_ports`) run here over
the in-memory repositories of the same contracts the PostgreSQL ones implement, and over a
recording stream writer in place of LangGraph's: the stop fence port denies a gated tool call
once the run's fence is persisted; the intent port writes the Operation Intent once per
effect, keyed on the tool call and the attempt's harness execution; the frame sink emits the
`mc.hook_invoked` / `mc.hook_result` custom events the frame recorder maps, kernel hooks
first and in kernel order; the usage port emits one `mc.usage` event per model answer with
the counts the recorder's `model.usage` body carries; and the callback mapper is the
identity over a script's own `mc.hook_input.v1`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import mission_control.adapters.deep_agents.hooks as hooks_module
from mission_control.adapters.deep_agents.frames import usage_counts
from mission_control.adapters.deep_agents.hooks import (
    HookContext,
    HookDispatcher,
    HookIntentLedgerShim,
    HookScriptMiddleware,
    KernelHookPorts,
    ResolvedHookScript,
    ScriptOutcome,
    StopFenceShim,
    StreamFrameSink,
    StreamUsageRecorder,
    hook_frame_events,
    hook_identity,
)
from mission_control.adapters.deep_agents.hooks_callback import (
    DeepAgentsHookMapper,
    callback_url,
    deep_agents_effect,
)
from mission_control.application.execution.harness.hook_callbacks import (
    HookTokenContext,
    InMemoryHookIntentLedger,
)
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.application.frames.kinds import classify
from mission_control.contracts.hooks import HookFrame, HookInput, HookScope, HookToolCall
from mission_control.domain.capabilities.hooks import KERNEL_HOOK_IDS, HookDecision, HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.lane_turns import INSTALLATION, SCOPE, TENANT

HEID = UUID("55555555-5555-4555-8555-555555555555")
RUN = "run-1"
HOOK_SCOPE = HookScope(
    installation_id=str(INSTALLATION), application_id="biotech", tenant_id=str(TENANT)
)


@dataclass
class RecordingWriter:
    """Stands in for the graph's stream writer (`langgraph.config.get_stream_writer`)."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, event: Any) -> None:
        self.events.append(dict(event))


@dataclass
class AllowRunner:
    calls: list[str] = field(default_factory=list)

    async def run(self, script: ResolvedHookScript, stdin: bytes, cwd: Path) -> ScriptOutcome:
        self.calls.append(script.hook_id)
        return ScriptOutcome(exit_code=0, stdout=b"")

    def run_sync(self, script: ResolvedHookScript, stdin: bytes, cwd: Path) -> ScriptOutcome:
        self.calls.append(script.hook_id)
        return ScriptOutcome(exit_code=0, stdout=b"")


@pytest.fixture
def writer(monkeypatch: pytest.MonkeyPatch) -> RecordingWriter:
    recording = RecordingWriter()
    monkeypatch.setattr(hooks_module, "get_stream_writer", lambda: recording)
    return recording


def _context(**changes: Any) -> HookContext:
    values: dict[str, Any] = {
        "scope": HOOK_SCOPE,
        "run_id": RUN,
        "activation_id": "op-1",
        "attempt_no": 1,
        "generation": 1,
        "harness_execution_id": str(HEID),
        "native_session_ref": "belllabs/stage/unit/gen/1",
        "workspace_root": "/hooks",
    }
    values.update(changes)
    return HookContext(**values)


def _dispatcher(
    ports: KernelHookPorts, *scripts: ResolvedHookScript, context: HookContext | None = None
) -> HookDispatcher:
    return HookDispatcher(
        context=context or _context(),
        kernel_hooks=ports.build(),
        scripts=scripts,
        runner=AllowRunner(),
        frames=ports.frames,
        cwd=Path(),
    )


def _script(hook_id: str, *events: HookEvent) -> ResolvedHookScript:
    return ResolvedHookScript(
        hook_id=hook_id, events=frozenset(events), interpreter="python", entrypoint=Path("h.py")
    )


def _shell(call_id: str) -> HookToolCall:
    return HookToolCall(name="shell", call_id=call_id, input={"command": "ls"})


# --- identity ---------------------------------------------------------------------------------


def test_hook_identity_is_the_runtime_unit_scope_and_the_recorder_execution() -> None:
    hook_input = _dispatcher(KernelHookPorts()).hook_input(HookEvent.BEFORE_TOOL)
    identity = hook_identity(hook_input)
    assert identity is not None
    assert identity.request_scope == SCOPE
    assert (identity.run_id, identity.generation, identity.harness_execution_id) == (RUN, 1, HEID)
    unbound = _dispatcher(
        KernelHookPorts(),
        context=HookContext(scope=HookScope(installation_id="unbound", application_id="unbound")),
    ).hook_input(HookEvent.BEFORE_TOOL)
    assert hook_identity(unbound) is None
    not_a_uuid = _dispatcher(
        KernelHookPorts(), context=_context(harness_execution_id="binding-1")
    ).hook_input(HookEvent.BEFORE_TOOL)
    assert hook_identity(not_a_uuid) is None


def test_effects_are_named_by_the_tool_call_and_classed_by_the_tool() -> None:
    effect = deep_agents_effect
    assert effect(HookEvent.BEFORE_SHELL, _shell("c1")) == ("tool_use:c1", "shell")
    assert effect(HookEvent.BEFORE_TOOL, HookToolCall(name="execute", call_id="x")) == (
        "tool_use:x",
        "shell",
    )
    assert effect(HookEvent.BEFORE_TOOL, HookToolCall(name="edit_file", call_id="e")) == (
        "tool_use:e",
        "file",
    )
    assert effect(HookEvent.BEFORE_MCP, HookToolCall(name="mcp__srv__look", call_id="m")) == (
        "tool_use:m",
        "mcp",
    )
    assert effect(HookEvent.SUBAGENT_START, HookToolCall(name="task", call_id="t")) == (
        "subagent:t",
        "task",
    )
    # The binding's class wins over the name; a call without an id is named by its digest.
    assert effect(HookEvent.BEFORE_TOOL, HookToolCall(name="x", side_effect_class="file")) == (
        effect(HookEvent.BEFORE_TOOL, HookToolCall(name="x", side_effect_class="file"))
    )
    declared = effect(HookEvent.BEFORE_TOOL, HookToolCall(name="x", side_effect_class="file"))
    assert declared is not None and declared[1] == "file"
    assert declared[0].startswith("tool_use:sha256:")
    assert effect(HookEvent.AFTER_TOOL, _shell("c1")) is None
    assert effect(HookEvent.BEFORE_TOOL, None) is None


# --- the stop fence port ------------------------------------------------------------------


async def test_the_fence_port_denies_a_tool_call_once_the_fence_is_set() -> None:
    fences = InMemoryStopFenceRepository()
    ports = KernelHookPorts(stop_fence=StopFenceShim(KernelHookFenceGate(fences)))
    runner = AllowRunner()
    dispatcher = HookDispatcher(
        context=_context(),
        kernel_hooks=ports.build(),
        scripts=(_script("hook.a", HookEvent.BEFORE_SHELL),),
        runner=runner,
        frames=ports.frames,
        cwd=Path(),
    )
    before = await dispatcher.dispatch(HookEvent.BEFORE_SHELL, tool=_shell("c1"))
    assert before.decision is HookDecision.ALLOW
    assert runner.calls == ["hook.a"]
    await fences.persist(
        StopFence(
            request_scope=SCOPE,
            run_id=RUN,
            generation=1,
            command_id="cancel-1",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    after = await dispatcher.dispatch(HookEvent.BEFORE_SHELL, tool=_shell("c2"))
    assert after.decision is HookDecision.DENY
    assert after.reason
    # The kernel deny short-circuits: the catalog hook never saw the fenced call.
    assert runner.calls == ["hook.a"]
    # The admission recorded before the fence stays admitted (idempotent per effect ref).
    again = await dispatcher.dispatch(HookEvent.BEFORE_SHELL, tool=_shell("c1"))
    assert again.decision is HookDecision.ALLOW
    # Observation events gate nothing and never consult the fence.
    observed = await dispatcher.dispatch(HookEvent.AFTER_SHELL, tool=_shell("c3"))
    assert observed.decision is HookDecision.ALLOW


async def test_the_fence_port_ignores_an_unbound_attempt() -> None:
    fences = InMemoryStopFenceRepository()
    await fences.persist(
        StopFence(
            request_scope=SCOPE,
            run_id=RUN,
            generation=1,
            command_id="cancel-1",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    ports = KernelHookPorts(stop_fence=StopFenceShim(KernelHookFenceGate(fences)))
    dispatcher = _dispatcher(ports, context=_context(run_id=None))
    result = await dispatcher.dispatch(HookEvent.BEFORE_TOOL, tool=_shell("c1"))
    assert result.decision is HookDecision.ALLOW


# --- the intent port ----------------------------------------------------------------------


async def test_the_intent_port_records_one_operation_intent_per_effect() -> None:
    ledger = InMemoryHookIntentLedger()
    clock = datetime(2026, 10, 21, 12, tzinfo=UTC)
    ports = KernelHookPorts(intents=HookIntentLedgerShim(ledger, clock=lambda: clock))
    dispatcher = _dispatcher(ports)
    tool = _shell("c1")
    # One shell call fires `before_tool` and `before_shell`; both name the same effect.
    for event in (HookEvent.BEFORE_TOOL, HookEvent.BEFORE_SHELL):
        result = await dispatcher.dispatch(event, tool=tool)
        assert result.decision is HookDecision.ALLOW
    (intent,) = ledger.intents()
    assert intent.request_scope == SCOPE
    assert (intent.run_id, intent.generation, intent.harness_execution_id) == (RUN, 1, HEID)
    assert (intent.effect_ref, intent.effect_kind) == ("tool_use:c1", "shell")
    assert intent.hook_event == "before_tool"
    assert intent.lane_profile == "deep_agents"
    assert intent.recorded_at == clock
    assert intent.input_digest.startswith("sha256:")
    # Observation events and unidentified calls write nothing.
    await dispatcher.dispatch(HookEvent.AFTER_TOOL, tool=tool)
    await dispatcher.dispatch(HookEvent.BEFORE_MODEL)
    assert len(ledger.intents()) == 1
    # A second call records its own intent.
    await dispatcher.dispatch(HookEvent.SUBAGENT_START, tool=HookToolCall(name="task", call_id="t"))
    assert [item.effect_ref for item in ledger.intents()] == ["tool_use:c1", "subagent:t"]


async def test_the_intent_port_writes_nothing_for_an_unbound_attempt() -> None:
    ledger = InMemoryHookIntentLedger()
    ports = KernelHookPorts(intents=HookIntentLedgerShim(ledger))
    dispatcher = _dispatcher(ports, context=_context(harness_execution_id="binding-1"))
    await dispatcher.dispatch(HookEvent.BEFORE_TOOL, tool=_shell("c1"))
    assert ledger.intents() == ()


# --- the frame sink -----------------------------------------------------------------------


async def test_the_frame_sink_emits_both_events_per_invocation_kernel_first(
    writer: RecordingWriter,
) -> None:
    sink = StreamFrameSink()
    ports = KernelHookPorts(frames=sink)
    dispatcher = _dispatcher(ports, _script("hook.a", HookEvent.BEFORE_SHELL))
    await dispatcher.dispatch(HookEvent.BEFORE_SHELL, tool=_shell("c1"))
    kinds = [event["type"] for event in writer.events]
    assert kinds == ["mc.hook_invoked", "mc.hook_result"] * 4
    invoked = [event for event in writer.events if event["type"] == "mc.hook_invoked"]
    # `mc.usage` does not observe `before_shell`; the three others precede the catalog hook.
    assert [event["hook_id"] for event in invoked] == [*KERNEL_HOOK_IDS[:3], "hook.a"]
    assert [event["kernel"] for event in invoked] == [True, True, True, False]
    # Tracing Stage 3 (R3-F8): the id names the gated tool call, never a sink-wide counter.
    assert all(event["invocation_ref"] == "call.c1" for event in writer.events)
    assert len({event["id"] for event in writer.events}) == 8
    assert all(event["tool_call_id"] == "c1" for event in writer.events)
    assert all(event["event"] == "before_shell" for event in writer.events)
    results = [event for event in writer.events if event["type"] == "mc.hook_result"]
    assert all(event["decision"] == "allow" and event["failed"] is False for event in results)
    assert all(event["result_digest"].startswith("sha256:") for event in results)
    assert sink.emitted == 4 and sink.dropped == 0
    # The recorder maps the raw kinds these events become (`custom.<type>`) to the hook frames.
    for event in writer.events:
        expected = (
            FrameKind.HOOK_INVOKED
            if event["type"] == "mc.hook_invoked"
            else (FrameKind.HOOK_RESULT)
        )
        classification = classify(LaneProfile.DEEP_AGENTS, f"custom.{event['type']}", event)
        assert classification.known and classification.kind is expected


def test_hook_frame_events_carry_the_frame_fields() -> None:
    frame = HookFrame(
        hook_id="hook.a",
        kernel=False,
        event=HookEvent.BEFORE_TOOL,
        lane_profile=LaneProfile.DEEP_AGENTS,
        decision=HookDecision.DENY,
        reason="no",
        input_digest="sha256:" + "a" * 64,
        result_digest="sha256:" + "b" * 64,
        tool_call_id="c9",
        duration_ms=7,
        failed=True,
    )
    invoked, result = hook_frame_events(frame, "call.c9")
    assert invoked == {
        "type": "mc.hook_invoked",
        "id": "hook:before_tool:hook.a:call.c9:invoked",
        "hook_id": "hook.a",
        "kernel": False,
        "event": "before_tool",
        "lane_profile": "deep_agents",
        "tool_call_id": "c9",
        "invocation_ref": "call.c9",
        "input_digest": "sha256:" + "a" * 64,
    }
    assert result == {
        "type": "mc.hook_result",
        "id": "hook:before_tool:hook.a:call.c9:result",
        "hook_id": "hook.a",
        "kernel": False,
        "event": "before_tool",
        "lane_profile": "deep_agents",
        "tool_call_id": "c9",
        "invocation_ref": "call.c9",
        "decision": "deny",
        "reason": "no",
        "result_digest": "sha256:" + "b" * 64,
        "duration_ms": 7,
        "failed": True,
    }


async def test_hook_frame_ids_do_not_depend_on_other_runs_of_the_worker(
    writer: RecordingWriter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tracing Stage 3 (R3-F8): one sink serves every run of a worker. The ids of a run's
    hook frames derive from the invocation (the tool call, else the LangGraph task of the
    model call), so a run that repeats a step after other runs used the sink (a retried
    activity) writes the same keys, and two tasks of one run never share one."""

    sink = StreamFrameSink()
    dispatcher = _dispatcher(KernelHookPorts(frames=sink))
    task = {"metadata": {"langgraph_checkpoint_ns": "model:task-a", "langgraph_step": 3}}
    monkeypatch.setattr(hooks_module, "get_config", lambda: task)
    await dispatcher.dispatch(HookEvent.BEFORE_MODEL)
    first = [event["id"] for event in writer.events]
    # Other runs use the same sink in between.
    for _ in range(3):
        await dispatcher.dispatch(HookEvent.BEFORE_TOOL, tool=_shell("other"))
    writer.events.clear()
    await dispatcher.dispatch(HookEvent.BEFORE_MODEL)
    assert [event["id"] for event in writer.events] == first
    assert all(event_id.split(":")[3].startswith("step.3.") for event_id in first)
    writer.events.clear()
    task["metadata"] = {"langgraph_checkpoint_ns": "tools:t|model:task-b", "langgraph_step": 3}
    await dispatcher.dispatch(HookEvent.BEFORE_MODEL)
    assert not {event["id"] for event in writer.events} & set(first)


async def test_the_frame_sink_drops_and_counts_outside_a_graph_run() -> None:
    sink = StreamFrameSink()
    dispatcher = _dispatcher(KernelHookPorts(frames=sink))
    await dispatcher.dispatch(HookEvent.BEFORE_TOOL, tool=_shell("c1"))
    assert sink.emitted == 0 and sink.dropped == 3


# --- the usage port -----------------------------------------------------------------------


@dataclass
class ModelRequest:
    messages: list[Any]
    state: dict[str, Any] = field(default_factory=dict)

    def override(self, **values: Any) -> ModelRequest:
        return ModelRequest(messages=values.get("messages", self.messages), state=self.state)


def test_the_usage_port_emits_one_usage_event_per_model_answer(writer: RecordingWriter) -> None:
    usage = StreamUsageRecorder()
    middleware = HookScriptMiddleware(_dispatcher(KernelHookPorts(usage=usage)))
    answer = AIMessage(
        id="msg-1",
        content="final",
        usage_metadata={"input_tokens": 12, "output_tokens": 5, "total_tokens": 17},
        response_metadata={"model_name": "fixture-model"},
    )
    request = ModelRequest(messages=[HumanMessage(content="go")])
    middleware.wrap_model_call(request, lambda _r: answer)
    events = [event for event in writer.events if event["type"] == "mc.usage"]
    # `mc.usage` also observes `stop` for this final answer; only `after_model` emits.
    assert [event["event"] for event in events] == ["after_model"]
    counts = usage_counts(answer.usage_metadata)
    (event,) = events
    assert event["id"] == "usage:msg-1"
    assert event["message_id"] == "msg-1" and event["model"] == "fixture-model"
    assert {key: event[key] for key in counts} == counts
    assert usage.emitted == 1 and usage.dropped == 0
    # An answer without usage emits nothing.
    writer.events.clear()
    middleware.wrap_model_call(
        ModelRequest(messages=[HumanMessage(content="go")]), lambda _r: AIMessage(content="x")
    )
    assert [event for event in writer.events if event["type"] == "mc.usage"] == []


async def test_the_usage_port_drops_and_counts_outside_a_graph_run() -> None:
    usage = StreamUsageRecorder()
    dispatcher = _dispatcher(KernelHookPorts(usage=usage))
    await dispatcher.dispatch(
        HookEvent.AFTER_MODEL,
        details={"message_id": "m", "usage": {"input_tokens": 1, "output_tokens": 1}},
    )
    assert usage.dropped == 1
    await dispatcher.dispatch(HookEvent.AFTER_MODEL)
    assert usage.dropped == 1


# --- the callback mapper ------------------------------------------------------------------


def test_the_callback_mapper_is_the_identity_with_the_token_identity() -> None:
    context = HookTokenContext(
        request_scope=SCOPE,
        run_id=RUN,
        attempt_no=2,
        generation=3,
        harness_execution_id=HEID,
        lane_profile="deep_agents",
        workspace_root="/hooks",
    )
    posted = _dispatcher(
        KernelHookPorts(), context=_context(run_id="forged", generation=9)
    ).hook_input(HookEvent.BEFORE_SHELL, tool=_shell("c1"), details={"note": "from the script"})
    payload = posted.model_dump(mode="json", exclude_none=True)
    mapper = DeepAgentsHookMapper()
    mapped = mapper.hook_input(HookEvent.BEFORE_SHELL, payload, context)
    assert isinstance(mapped, HookInput)
    assert mapped.lane_profile is LaneProfile.DEEP_AGENTS
    assert mapped.scope == HOOK_SCOPE
    # Identity comes from the verified token, never from the posted payload.
    assert (mapped.run_id, mapped.attempt_no, mapped.generation) == (RUN, 2, 3)
    assert mapped.harness_execution_id == str(HEID)
    assert mapped.workspace_root == "/hooks"
    assert mapped.tool == _shell("c1")
    assert mapped.details == {"note": "from the script"}
    assert mapped.native_session_ref == "belllabs/stage/unit/gen/1"
    assert mapped.provider_payload_digest and mapped.provider_payload_digest.startswith("sha256:")
    assert mapper.effect(HookEvent.BEFORE_SHELL, payload) == ("tool_use:c1", "shell")
    assert mapper.effect(HookEvent.AFTER_SHELL, payload) is None
    assert mapper.hook_input(HookEvent.STOP, {"tool": "not a mapping"}, context).tool is None
    assert callback_url("http://127.0.0.1:47555/", SCOPE) == (
        "http://127.0.0.1:47555/v1/applications/biotech/internal/hook-callback"
    )

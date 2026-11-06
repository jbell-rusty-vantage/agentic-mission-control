"""Durable native review, readiness ordering and fenced answers; fixture provider only."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.application.execution.approvals_memory import StaticApprovalContext
from mission_control.application.execution.harness.hook_callbacks import InMemoryHookIntentLedger
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.hosted_tools import HostedCall, HostedToolGate
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.managed_lane import managed_stack
from tests.unit.anthropic_managed.test_harness import _started
from tests.unit.approvals.fixtures import answer
from tests.unit.approvals.test_approval_broker import OWNER, _compose


def gate(stack, *, wait=1.0):
    fences, intents = InMemoryStopFenceRepository(), InMemoryHookIntentLedger()
    broker, human, store, _ = _compose(
        context=StaticApprovalContext(1, stack.operation.effective_configuration_digest),
        fences=fences,
    )
    human = HumanTaskService(
        InMemoryHumanTaskRepository(),
        request_scope=stack.operation.request_scope,
        approvals=store,
        approval_wake=broker.hub,
    )
    runtime = HostedToolGate(
        fences=fences,
        intents=intents,
        broker=broker,
        reviewers=("owner",),
        allowed_tools=frozenset({"bash", "mc_signal", "mc_prepare"}),
        wait_seconds=wait,
    )
    return runtime, human, store, fences, intents


async def test_native_permission_round_trip_and_replay(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    identity = LaneExecutionIdentity.of(stack.operation, "claude_managed", 1)
    runtime, human, store, _, intents = gate(stack)
    call = HostedCall("session", "turn", "call", "bash", {"command": "echo bounded"})
    waiting = asyncio.create_task(runtime.permission(stack.operation, identity, call, "shell"))
    for _ in range(100):
        tasks = await store.list_tasks(identity.request_scope)
        if tasks:
            break
        await asyncio.sleep(0.001)
    (task,) = tasks
    await human.resolve(task.human_task_id, answer(task), OWNER)
    assert await waiting == {"result": "allow"}
    assert await runtime.permission(stack.operation, identity, call, "shell") == {"result": "allow"}
    assert len(intents.intents()) == 1
    assert len(await store.list_tasks(identity.request_scope)) == 1


async def test_timeout_leaves_provider_wait_and_task_open(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    identity = LaneExecutionIdentity.of(stack.operation, "claude_managed", 1)
    runtime, _, store, _, _ = gate(stack, wait=0.01)
    result = await runtime.permission(
        stack.operation,
        identity,
        HostedCall("session", "turn", "call", "bash", {"command": "echo bounded"}),
        "shell",
    )
    assert result is None
    assert (await store.list_tasks(identity.request_scope))[0].lifecycle == "open"


async def test_stop_fence_refuses_answer_before_opening_human_task(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    identity = LaneExecutionIdentity.of(stack.operation, "claude_managed", 1)
    runtime, _, store, fences, intents = gate(stack)
    await fences.persist(
        StopFence(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            generation=1,
            command_id="cancel",
            reason="stop",
            requested_at=datetime.now(UTC),
        )
    )
    result = await runtime.permission(
        stack.operation,
        identity,
        HostedCall("session", "turn", "call", "bash", {"command": "echo bounded"}),
        "shell",
    )
    assert result["result"] == "deny"
    assert not await store.list_tasks(identity.request_scope)
    assert not intents.intents()


async def test_env_prepared_requires_mc_prepare_and_successful_setup(tmp_path: Path) -> None:
    stack = managed_stack(tmp_path)
    _, session = await _started(stack)
    identity = LaneExecutionIdentity.of(stack.operation, "claude_managed", 1)
    runtime, _, _, _, _ = gate(stack)
    signals = []

    async def signal(_identity, call):
        signals.append(call)
        return {"accepted": 1}

    tools = ManagedTools(
        client=stack.api.client(),
        gate=runtime,
        governed=None,
        signal=signal,
        setup_commands=("echo setup",),
        steady_tools=stack.pack.agent_body([])["tools"],
    )
    api = stack.api
    sid = session.native_session_ref

    async def pending(name, arguments, kind="agent.custom_tool_use"):
        event = {"type": kind, "id": api._id("sevt"), "name": name, "input": arguments}
        api._append(sid, event)
        api.sessions[sid]["status"] = "idle"
        idle = {"stop_reason": {"type": "requires_action", "event_ids": [event["id"]]}}
        await tools.answer_pending(stack.operation, identity, sid, "turn", idle)
        return event

    await pending("mc_signal", {"name": "env.prepared"})
    assert not signals
    assert api.sent[-1][1]["is_error"]
    await pending("mc_prepare", {})
    await pending("mc_signal", {"name": "env.prepared"})
    assert not signals
    setup = await pending("bash", {"command": "echo setup"}, "agent.tool_use")
    assert api.sent[-1][1]["result"] == "allow"
    api._append(sid, {"type": "agent.tool_result", "tool_use_id": setup["id"], "is_error": False})
    await pending("mc_signal", {"name": "env.prepared"})
    assert len(signals) == 1
    assert not api.sent[-1][1]["is_error"]


@pytest.mark.parametrize("mode", ["delayed", "missing", "wrong_path"])
async def test_publication_waits_boundedly_for_scoped_bundle(tmp_path, mode):
    from mission_control.application.effects.mission_branches import mission_branch

    stack = managed_stack(tmp_path)
    binding = ProviderExecutionBinding.sealed(
        **{
            **ProviderExecutionBinding.carried_by(stack.operation).model_dump(
                exclude={"binding_digest"}
            ),
            "repo_url": "https://github.com/owner/repo",
            "repo_ref": "main",
            "repo_commit": "a" * 40,
        }
    )
    operation = stack.operation.model_copy(update={**lane_fields(binding)})
    identity = LaneExecutionIdentity.of(operation, "claude_managed", 1)
    reads, calls = [], []

    class Files:
        async def session_files(self, session_id):
            reads.append(session_id)
            if mode == "missing" or len(reads) == 1:
                return []
            return [
                {
                    "id": "file-scoped",
                    "filename": "mc.bundle" if mode == "delayed" else "other.bundle",
                }
            ]

        async def download_file(self, file_id):
            assert file_id == "file-scoped"
            return b"bounded fixture bundle"

    class Governed:
        async def execute(self, operation, identity, call):
            calls.append(call)
            return {"status": "executed", "receipt": {"outcome": "applied"}}

    runtime, _, _, _, _ = gate(stack)
    tools = ManagedTools(
        client=Files(),
        gate=runtime,
        governed=Governed(),
        signal=None,
        artifacts=stack.artifacts,
        steady_tools=stack.pack.agent_body([])["tools"],
        custody_wait_seconds=0.05,
    )
    call = HostedCall(
        "session-scoped",
        "turn",
        "original-call",
        "mc_publish",
        {"branch": mission_branch(identity.run_key, identity.activation_key)},
    )
    result = await tools._publish(operation, identity, call)
    assert len(reads) >= 2 and set(reads) == {call.session_id}
    if mode == "delayed":
        assert result["status"] == "executed" and len(calls) == 2
        assert all(
            item.call_id == call.call_id and item.session_id == call.session_id for item in calls
        )
    else:
        assert result["required_action"] == "write_bundle" and not calls

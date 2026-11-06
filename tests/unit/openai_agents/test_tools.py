"""Required-action approval round trip and real git publication from durable upload custody."""

import asyncio
import base64
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from mission_control.adapters.openai_agents.tools import AgentsTools
from mission_control.adapters.remote_session.function_custody import (
    CustodiedBundlePublishExecutor,
    HostedArtifactUploadExecutor,
)
from mission_control.adapters.remote_session.stream import poll_while_idle
from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.adapters.workspaces.git_workspaces import run_git
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.execution.approvals_governed import (
    GOVERNED_EFFECT_PERMISSION,
    GovernedEffectService,
    GovernedTool,
    GovernedToolPolicy,
    GovernedToolRegistry,
)
from mission_control.application.execution.approvals_memory import (
    InMemoryGovernedIntents,
    StaticApprovalContext,
)
from mission_control.application.execution.harness.hook_callbacks import InMemoryHookIntentLedger
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.hosted_tools import HostedGovernedTools, HostedToolGate
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.agents_lane import agents_stack
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.approvals.fixtures import answer
from tests.unit.approvals.test_approval_broker import OWNER, _compose
from tests.unit.effects.test_hosted_bundle_publication import NoCredential, repository


class PendingClient:
    def __init__(self):
        self.actions = []
        self.results = []
        self.records = []
        self.history = {}
        self.turn_records = []

    def pending(self, name, arguments, *, turn="turn", call="call"):
        self.actions = [
            {
                "type": "function_call",
                "name": name,
                "arguments": arguments,
                "turn_id": turn,
                "call_id": call,
            }
        ]

    async def retrieve_session(self, session):
        return {"status": "requires_action", "required_actions": list(self.actions)}

    async def turns(self, session):
        for turn in self.turn_records:
            yield turn

    async def items(self, session, *, turn_id):
        for item in self.history.get(turn_id, self.records):
            yield item

    async def send_events(self, session, events, *, idempotency_key):
        self.results.extend(events)
        self.actions = []


class Custody:
    def __init__(self):
        self.blobs = {}

    async def stage(self, *, request_scope, name, content, media_type):
        ref = "custody:" + sha256((request_scope + name).encode() + content).hexdigest()
        self.blobs[ref] = content
        return ref

    async def retrieve(self, ref):
        return self.blobs[ref]


class Host:
    async def branch_head(self, repository, branch):
        result = run_git(
            "ls-remote", "--heads", repository, "refs/heads/" + branch, cwd=Path(repository)
        ).split()
        return result[0].decode() if result else None


class Stack:
    def __init__(self, operation, root, *, wait=1):
        self.operation = operation
        self.identity = LaneExecutionIdentity.of(operation, "codex_agents", 1)
        self.client, self.artifacts = PendingClient(), Custody()
        self.fences, self.ledger = InMemoryStopFenceRepository(), InMemoryHookIntentLedger()
        context = StaticApprovalContext(1, operation.effective_configuration_digest)
        broker, _, self.tasks, _ = _compose(context=context, fences=self.fences)
        self.human = HumanTaskService(
            InMemoryHumanTaskRepository(),
            request_scope=operation.request_scope,
            approvals=self.tasks,
            approval_wake=broker.hub,
        )
        self.intents = InMemoryGovernedIntents()
        registry = GovernedToolRegistry(
            [
                GovernedTool(
                    "mc_upload_artifact",
                    HostedArtifactUploadExecutor(self.artifacts, self.identity),
                    GovernedToolPolicy(requires_approval=False),
                    effect_kind="file",
                ),
                GovernedTool(
                    "mc_publish",
                    CustodiedBundlePublishExecutor(
                        artifacts=self.artifacts,
                        intents=self.intents,
                        publisher=GitBundlePublisher(root / "publisher", NoCredential()),
                        host=Host(),
                        operation=operation,
                        identity=self.identity,
                    ),
                    GovernedToolPolicy(reviewers=("owner",)),
                    effect_kind="other",
                ),
            ]
        )
        service = GovernedEffectService(
            self.intents,
            self.tasks,
            registry,
            request_scope=operation.request_scope,
            probe=context,
            fences=self.fences,
        )
        gate = HostedToolGate(
            fences=self.fences,
            intents=self.ledger,
            broker=broker,
            reviewers=("owner",),
            allowed_tools=frozenset(
                {
                    "mc_request_approval",
                    "mc_upload_artifact",
                    "mc_publish",
                    "mc_signal",
                    "mc_prepare",
                }
            ),
            wait_seconds=wait,
        )

        async def signal(identity, call):
            return {"status": "accepted"}

        self.tools = AgentsTools(
            client=self.client,
            gate=gate,
            governed=HostedGovernedTools(
                lambda op, identity: service,
                ActorContext(
                    actor_id="runtime", permissions=frozenset({GOVERNED_EFFECT_PERMISSION})
                ),
            ),
            artifacts=self.artifacts,
            signal=signal,
            secrets=SecretValueRegistry(),
        )

    async def tick(self):
        await self.tools.answer_pending(self.operation, self.identity, "session", "turn")

    async def approve(self):
        tasks = await self.tasks.list_tasks(self.operation.request_scope, lifecycle="open")
        assert tasks
        for task in tasks:
            await self.human.resolve(task.human_task_id, answer(task), OWNER)


async def test_required_action_waits_for_human_and_replay_does_not_duplicate(tmp_path):
    stack = Stack(agents_stack(tmp_path).operation, tmp_path)
    stack.client.pending("mc_request_approval", {"action": "bounded action"})
    pending = asyncio.create_task(stack.tick())
    for _ in range(100):
        if await stack.tasks.list_tasks(stack.operation.request_scope):
            break
        await asyncio.sleep(0.001)
    await stack.approve()
    await pending
    assert stack.client.results[0]["success"] is True
    assert json.loads(stack.client.results[0]["output"]) == {"result": "allow"}
    await stack.tick()
    assert len(stack.client.results) == 1 and len(stack.ledger.intents()) == 1


async def test_timeout_preserves_pending_and_subagent_calls_are_ignored(tmp_path):
    stack = Stack(agents_stack(tmp_path).operation, tmp_path, wait=0.01)
    stack.client.pending("mc_request_approval", {}, turn="subagent-turn")
    await stack.tick()
    assert not stack.client.results and not stack.ledger.intents()
    stack.client.pending("mc_request_approval", {})
    await stack.tick()
    assert stack.client.actions and not stack.client.results
    assert (await stack.tasks.list_tasks(stack.operation.request_scope))[0].lifecycle == "open"


async def test_fence_refuses_before_effect_intent_and_tool_answer_is_failure(tmp_path):
    stack = Stack(agents_stack(tmp_path).operation, tmp_path)
    await stack.fences.persist(
        StopFence(
            request_scope=stack.operation.request_scope,
            run_id=stack.identity.run_key,
            generation=1,
            command_id="cancel",
            reason="stop",
            requested_at=datetime.now(UTC),
        )
    )
    stack.client.pending("mc_signal", {"name": "findings.ready"})
    await stack.tick()
    assert stack.client.results[0]["success"] is False
    assert not stack.ledger.intents()


async def test_verified_bundle_is_custodied_before_review_then_published_once(tmp_path):
    operation = agents_stack(tmp_path).operation
    source, remote, base = repository(tmp_path)
    identity = LaneExecutionIdentity.of(operation, "codex_agents", 1)
    branch = mission_branch(identity.run_key, identity.activation_key)
    run_git("branch", "-m", branch, cwd=source)
    (source / "result.txt").write_text("real-git-evidence\n")
    run_git("add", ".", cwd=source)
    run_git("commit", "-q", "-m", "evidence", cwd=source)
    target = tmp_path / "mc.bundle"
    run_git("bundle", "create", str(target), branch, "^" + base, cwd=source)
    head = run_git("rev-parse", "HEAD", cwd=source).decode().strip()
    binding = ProviderExecutionBinding.sealed(
        **{
            **ProviderExecutionBinding.carried_by(operation).model_dump(exclude={"binding_digest"}),
            "repo_url": str(remote),
            "repo_ref": "main",
            "repo_commit": base,
        }
    )
    stack = Stack(operation.model_copy(update={**lane_fields(binding)}), tmp_path)
    stack.client.pending(
        "mc_upload_artifact",
        {
            "path": "/workspace/outputs/mc.bundle",
            "content_base64": base64.b64encode(target.read_bytes()).decode(),
        },
        call="upload",
    )
    await stack.tick()
    uploaded = json.loads(stack.client.results[-1]["output"])
    assert uploaded["status"] == "executed"
    stack.client.pending("mc_publish", {"upload_intent_id": uploaded["intent_id"]}, call="publish")
    await stack.tick()
    assert stack.client.actions  # human review still pending, branch not written
    assert await Host().branch_head(str(remote), branch) is None

    async def quiet_stream():
        await asyncio.Event().wait()
        yield None

    # The initial tool wait returned pending. Approval arrives while the provider SSE
    # emits nothing; the observer's durable poll must deliver the original result.
    observer = asyncio.create_task(
        anext(poll_while_idle(quiet_stream(), stack.tick, interval_s=0.01))
    )
    try:
        await asyncio.sleep(0.03)
        assert stack.client.actions
        await stack.approve()
        for _ in range(1000):
            if observer.done():
                await observer
            if not stack.client.actions:
                break
            await asyncio.sleep(0.01)
        assert not stack.client.actions
    finally:
        observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
    assert json.loads(stack.client.results[-1]["output"])["receipt"]["output"]["head_sha"] == head
    assert await Host().branch_head(str(remote), branch) == head
    assert await Host().branch_head(str(remote), "main") == base
    await stack.tick()
    assert len(await stack.tasks.list_tasks(stack.operation.request_scope)) == 1


async def test_prepared_signal_requires_offered_setup_and_provider_success_records(tmp_path):
    stack = Stack(agents_stack(tmp_path).operation, tmp_path)

    async def setup(operation, identity):
        return ("echo trusted-setup",)

    stack.tools.setup_commands = setup
    stack.client.pending("mc_signal", {"name": "env.prepared"})
    await stack.tick()
    assert stack.client.results[-1]["error"] == "mission_layer_not_completed"
    stack.client.records = [
        {"type": "function_call", "name": "mc_prepare", "call_id": "prepare"},
        {
            "type": "command_execution",
            "status": "completed",
            "command": "echo trusted-setup",
            "exit_code": 1,
        },
    ]
    stack.client.pending("mc_signal", {"name": "env.prepared"})
    await stack.tick()
    assert stack.client.results[-1]["success"] is False
    stack.client.records[-1]["exit_code"] = 0
    stack.client.pending("mc_signal", {"name": "env.prepared"})
    await stack.tick()
    assert json.loads(stack.client.results[-1]["output"])["status"] == "recorded"


@pytest.mark.parametrize("invalid", [None, "subagent", "incomplete", "binding", "command"])
async def test_preparation_restores_only_sealed_completed_root_turn(tmp_path, invalid):
    stack = Stack(agents_stack(tmp_path).operation, tmp_path)

    async def setup(operation, identity):
        return ("echo trusted-setup",)

    stack.tools.setup_commands = setup
    stack.client.pending("mc_prepare", {})
    await stack.tick()
    prepared = json.loads(stack.client.results[-1]["output"])
    previous = [
        {"type": "function_call", "name": "mc_prepare", "call_id": "prepare"},
        {"type": "function_call_output", "call_id": "prepare", "output": prepared},
        {
            "type": "command_execution",
            "command": "echo trusted-setup",
            "status": "completed",
            "exit_code": 0,
        },
        {
            "type": "function_call",
            "name": "mc_signal",
            "call_id": "signal",
            "arguments": {"name": "env.prepared"},
        },
        {"type": "function_call_output", "call_id": "signal", "output": {"status": "recorded"}},
    ]
    turn = {"id": "previous", "status": "completed"}
    if invalid == "subagent":
        turn["subagent_id"] = "nested"
    elif invalid == "incomplete":
        turn["status"] = "failed"
    elif invalid == "binding":
        prepared["preparation_digest"] = "sha256:" + "0" * 64
    elif invalid == "command":
        previous[2]["command"] = "echo another-command"
    stack.client.turn_records = [turn]
    stack.client.history = {"previous": previous}
    stack.client.pending(
        "mc_upload_artifact",
        {"path": "/workspace/outputs/evidence.txt", "content_base64": "Ym91bmRlZA=="},
    )
    await stack.tick()
    result = stack.client.results[-1]
    output = json.loads(result["output"]) if result["success"] else result
    assert (output.get("error") == "environment_not_prepared") == (invalid is not None)
    if invalid is None:
        assert output["status"] == "executed"

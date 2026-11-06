"""Opt-in S3 real Agents API approval/recovery; isolated PG/Temporal and zero vaults."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import uuid4

import pytest
from pydantic import SecretStr
from tests.fixtures.agents_lane import agents_stack
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.anthropic_managed.test_managed_segment_loop_real_services import (
    _activity_worker,
    _client,
    _replayed,
    _workflow_worker,
)
from tests.integration.anthropic_managed.test_session_lifecycle_live import _request
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.approvals.fixtures import answer

from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.harness import CodexAgentsHarness
from mission_control.adapters.openai_agents.pack import load_pack
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.openai_agents.tools import AgentsTools
from mission_control.adapters.operations.conformance import ConformanceRuntime
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.lanes.hook_tokens import PostgresHookIntentLedger
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.provider_lane_composition import compose_approval_broker
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    LaneTurnService,
)
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.application.execution.harness.sessions import WorkerSessionManager
from mission_control.application.execution.hosted_tools import HostedToolGate
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.policies.contracts import ActorContext

LIVE = os.environ.get("MC_HL13_LIVE") == "1" and bool(os.environ.get("OPENAI_API_KEY"))
pytestmark = pytest.mark.skipif(
    not LIVE, reason="S3 requires successful R27 and explicit paid opt-in"
)


class TrackedClient(AgentsApiClient):
    def __init__(self):
        super().__init__(SecretStr(os.environ["OPENAI_API_KEY"]))
        self.created_agents, self.created_templates, self.created_sessions = [], [], []
        self.messages = 0
        self.failures = []
        self.turn_reads = []
        self.dispatch_errors = []
        self.tool_results = []
        self.requests = []
        request_starts = {}

        async def request_hook(request):
            item = {
                "method": request.method,
                "path": request.url.path,
                "accept": request.headers.get("accept"),
                "started": monotonic(),
            }
            request_starts[id(request)] = item
            self.requests.append(item)

        self._client.event_hooks["request"].append(request_hook)

        async def response_hook(response):
            item = request_starts.get(id(response.request), {})
            item.update(
                status=response.status_code,
                headers_after_s=round(monotonic() - item.get("started", monotonic()), 3),
                content_type=response.headers.get("content-type"),
            )
            if response.status_code >= 400:
                await response.aread()
                try:
                    body = response.json().get("error", {})
                except ValueError:
                    body = {}
                self.failures.append(
                    {
                        "status": response.status_code,
                        "method": response.request.method,
                        "path": response.request.url.path,
                        "code": body.get("code"),
                        "type": body.get("type"),
                    }
                )

        self._client.event_hooks["response"].append(response_hook)

    async def create_agent(self, body):
        row = await super().create_agent(body)
        self.created_agents.append(row["id"])
        return row

    async def create_environment_template(self, body):
        row = await super().create_environment_template(body)
        self.created_templates.append(row["id"])
        return row

    async def create_session(self, body):
        row = await super().create_session(body)
        self.created_sessions.append(row["id"])
        return row

    async def turns(self, session_id):
        rows = [row async for row in super().turns(session_id)]
        self.turn_reads.append(
            [{key: row.get(key) for key in ("id", "status", "subagent_id")} for row in rows]
        )
        for row in rows:
            yield row

    async def send_events(self, session_id, events, *, idempotency_key):
        self.messages += sum(event.get("type") == "agent.session.input.message" for event in events)
        result = await super().send_events(session_id, events, idempotency_key=idempotency_key)
        for event in events:
            if event.get("type") == "agent.session.input.tool_result":
                self.tool_results.append(dict(event))
        return result


class TrackedHarness(CodexAgentsHarness):
    async def send_turn(self, request):
        try:
            return await super().send_turn(request)
        except BaseException as error:
            self._client.dispatch_errors.append({"type": type(error).__name__})
            raise


def drill_pack(tmp_path: Path, stamp: str):
    instructions = (
        "Call mc_request_approval exactly once with action bounded-live-proof. "
        "Wait for approval, then reply HL13-OK and stop. "
        "Do not run shell commands or use other tools."
    )
    document = {
        "schema_version": "mc.hosted_pack.codex_agents.v1",
        "application": "ai-engineer",
        "lane_profile": "codex_agents",
        "tool_placement": "openai_hosted",
        "data_class": "internal",
        "task_queue": "hl13-live-" + stamp,
        "agent": {
            "name": "mc-hl13-live-" + stamp,
            "model": "gpt-6-luna",
            "reasoning_effort": "low",
            "instructions": "instructions.md",
            "multi_agent": False,
            "function_tools": [
                {
                    "name": "mc_request_approval",
                    "description": "Ask the owner to approve this bounded drill action.",
                    "parameters": {
                        "type": "object",
                        "properties": {"action": {"type": "string"}},
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
        "environment": {"container_size": "small", "network": {"access": "disabled"}},
        "vault": {"credentials": []},
    }
    (tmp_path / "pack.yaml").write_text(json.dumps(document))
    (tmp_path / "instructions.md").write_text(instructions)
    pack = load_pack(tmp_path)
    return pack, instructions


@pytest.mark.common_db
async def test_live_function_review_survives_worker_restart(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
):
    allowance = Decimal(os.environ["MC_PAID_BUDGET_USD"])
    assert allowance.is_finite() and 0 < allowance <= 10
    evidence = Path(os.environ["MC_HL13_EVIDENCE"])
    assert evidence.parent.is_dir()
    stamp = uuid4().hex[:10]
    pack, instructions = drill_pack(tmp_path, stamp)
    api = TrackedClient()
    preparer = CodexAgentsPreparer(
        api, WorkerEnvironmentSource({}), labels={"mc_run": "run1-HL13-" + stamp}
    )
    pool = await common_db.pool("mission_control_runtime")
    record = {
        "model": "gpt-6-luna",
        "cost_disposition": "unknown",
        "vaults": 0,
        "network_hosts": [],
        "cleanup": {},
    }
    try:
        admitted = await admit_unit_attempt(pool, common_db)
        stack = agents_stack(tmp_path)
        binding = ProviderExecutionBinding.sealed(
            **{
                **ProviderExecutionBinding.carried_by(stack.operation).model_dump(
                    exclude={"binding_digest"}
                ),
                "materialization_digest": pack.digest,
                "task_queue": pack.document.task_queue,
                "budgets": {"max_turns": 1, "max_segments": 8, "wall_clock_s": 120},
            }
        )
        operation = OperationExecutionRequest.model_validate(
            {
                **stack.operation.model_dump(mode="python"),
                **lane_fields(binding),
                "request_scope": admitted.unit.request_scope,
                "runtime_unit": admitted.unit,
                "identity": OperationAttemptIdentity(
                    run_id=admitted.run_key,
                    operation_id=admitted.unit.semantic_operation_id,
                    operation_attempt=admitted.unit.semantic_attempt,
                ),
                "budget_limits": {"model.turns": 1, "tokens.total": 4000},
                "prompt_segments": [
                    {
                        **stack.operation.prompt_segments[0].model_dump(),
                        "content": instructions,
                        "rendered_digest": sha256_digest(instructions),
                    }
                ],
            }
        )
        identity = LaneExecutionIdentity.of(operation, "codex_agents", 1)
        tasks = PostgresApprovalTaskRepository(pool)
        broker = compose_approval_broker(pool, connection_ref="hl13-live")
        human = HumanTaskService(
            PostgresHumanTaskRepository(pool),
            request_scope=identity.request_scope,
            approvals=tasks,
            approval_wake=broker.hub,
        )
        gate = HostedToolGate(
            fences=PostgresStopFenceRepository(pool),
            intents=PostgresHookIntentLedger(pool),
            broker=broker,
            reviewers=("owner",),
            allowed_tools=frozenset({"mc_request_approval"}),
            wait_seconds=0.01,
        )
        tools = AgentsTools(
            client=api,
            gate=gate,
            governed=None,
            signal=None,
            artifacts=stack.artifacts,
            secrets=SecretValueRegistry(),
        )

        def harness():
            return TrackedHarness(
                client=api,
                preparer=preparer,
                pack=pack,
                artifacts=stack.artifacts,
                retention=SessionRetentionService(stack.deletions),
                tools=tools,
                labels={"mc_run": "run1-HL13-" + stamp},
            )

        first = harness()
        lanes = lane_stack(first, operation=operation)
        frames, states = PostgresFrameRepository(pool), PostgresLaneExecutionStateStore(pool)

        def service(lane, owner):
            return LaneTurnService(
                lanes=LaneRegistry(
                    [DeepAgentsHarness(ConformanceRuntime()), lane], allow_unqualified=True
                ),
                boundary=lanes.boundary,
                frames=frames,
                states=states,
                frame_reader=frames,
                sessions=WorkerSessionManager(owner_ref=owner, min_lease=timedelta(seconds=1)),
            )

        temporal = await _client()
        async with _workflow_worker(temporal, "hl13-wf-" + stamp):
            dying = _activity_worker(
                temporal,
                pack.document.task_queue,
                lanes.boundary,
                service(first, "hl13-a-" + stamp),
            )
            running = asyncio.create_task(dying.run())
            handle = await temporal.start_workflow(
                OperationWorkflow.run,
                _request(operation),
                id="hl13-live-" + stamp,
                task_queue="hl13-wf-" + stamp,
                execution_timeout=timedelta(seconds=300),
            )
            try:
                for poll in range(4000):
                    pending = await tasks.list_tasks(
                        identity.request_scope, run_id=identity.run_key, lifecycle="open"
                    )
                    if pending:
                        break
                    if api.created_sessions and poll % 100 == 0:
                        state = await api.retrieve_session(api.created_sessions[-1])
                        record["pending_native_state"] = {
                            "status": state.get("status"),
                            "actions": [
                                {
                                    key: item.get(key)
                                    for key in ("type", "name", "turn_id", "call_id")
                                }
                                for item in state.get("required_actions", [])
                            ],
                        }
                    if running.done():
                        await running
                    await asyncio.sleep(0.05)
                assert len(pending) == 1, "provider never requested bounded function approval"
            finally:
                await dying.shutdown()
                await asyncio.gather(running, return_exceptions=True)
            await human.resolve(
                pending[0].human_task_id, answer(pending[0]), ActorContext(actor_id="owner")
            )
            resolved = await tasks.get(identity.request_scope, pending[0].human_task_id)
            assert resolved is not None and resolved.lifecycle == "resolved"
            assert resolved.resolution is not None and resolved.resolution.decision == "approve"
            async with _activity_worker(
                temporal,
                pack.document.task_queue,
                lanes.boundary,
                service(harness(), "hl13-b-" + stamp),
            ):
                result = await asyncio.wait_for(handle.result(), 300)
            await _replayed(handle)
        stored = await frames.frames_for_execution(
            identity.request_scope, identity.harness_execution_id, 1, limit=1000
        )
        record.update(
            disposition=result.disposition,
            frames=len(stored),
            duplicate_keys=len(stored) - len({frame.provider_key for frame in stored}),
            input_messages=api.messages,
            sessions=len(api.created_sessions),
            human_tasks=1,
            worker_restart=True,
        )
        assert result.disposition == "completed" and api.messages == len(api.created_sessions) == 1
        assert record["duplicate_keys"] == 0
        expected = pending[0].packet.binding.native
        assert expected.native_session_ref == api.created_sessions[0]
        assert expected.native_request_ref is not None and expected.native_turn_ref is not None
        delivered = [
            event
            for event in api.tool_results
            if event["call_id"] == expected.native_request_ref
            and event["turn_id"] == expected.native_turn_ref
        ]
        assert len(delivered) == 1 and delivered[0]["success"] is True
        assert json.loads(delivered[0]["output"])["result"] == "allow"
    except Exception as error:
        record["failure_type"] = type(error).__name__
        raise
    finally:
        for session in api.created_sessions:
            try:
                async for turn in api.turns(session):
                    if turn.get("status") not in {"completed", "failed", "cancelled"}:
                        await api.send_events(
                            session,
                            [{"type": "agent.session.input.cancel"}],
                            idempotency_key="hl13-cleanup-" + stamp,
                        )
                for _ in range(60):
                    if (await api.retrieve_session(session)).get("status") == "idle":
                        break
                    await asyncio.sleep(0.5)
                record.setdefault("native_usage", []).extend(
                    [
                        {key: turn.get(key) for key in ("id", "status", "usage")}
                        async for turn in api.turns(session)
                    ]
                )
                await api.delete_session(session)
                record["cleanup"][session] = "deleted"
            except Exception as error:
                record["cleanup"][session] = type(error).__name__
        for ids, delete in (
            (api.created_agents, api.delete_agent),
            (api.created_templates, api.delete_environment_template),
        ):
            for resource in ids:
                try:
                    await delete(resource)
                    record["cleanup"][resource] = "deleted"
                except Exception as error:
                    record["cleanup"][resource] = type(error).__name__
        record["provider_failures"] = api.failures
        record["dispatch_errors"] = api.dispatch_errors
        record["workflow_bound_s"] = 300
        record["activity_start_to_close_s"] = 300
        record["request_timings"] = [
            {key: value for key, value in item.items() if key != "started"} for item in api.requests
        ]
        record["input_messages"] = api.messages
        record["sessions"] = len(api.created_sessions)
        record["turn_reads_first"] = api.turn_reads[:4]
        record["turn_reads_last"] = api.turn_reads[-4:]
        record["cleanup_complete"] = all(value == "deleted" for value in record["cleanup"].values())
        await asyncio.to_thread(evidence.write_text, json.dumps(record, indent=2, sort_keys=True))
        await api.aclose()
        await pool.close()
        assert all(value == "deleted" for value in record["cleanup"].values())

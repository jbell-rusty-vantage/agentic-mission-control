"""Opt-in S2: live Managed Agents approval+bundle, local Temporal/PG and real local git.

No vault, secret, outbound network host, repository mount or GitHub write is used.
The PR host below is explicitly a fixture; it proves gateway use, not a live GitHub PR.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from pydantic import SecretStr
from temporalio.client import Client
from temporalio.worker import Worker

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.harness import ClaudeManagedHarness
from mission_control.adapters.anthropic_managed.pack import load_pack, render_pack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.anthropic_managed.publication import ManagedPublishExecutor
from mission_control.adapters.anthropic_managed.tools import ManagedTools
from mission_control.adapters.postgres.approvals.context import PostgresApprovalContextProbe
from mission_control.adapters.postgres.approvals.intents import PostgresGovernedIntentRepository
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.lanes.hook_tokens import PostgresHookIntentLedger
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.remote_session.signals import HostedSignalDelivery
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.local_signals import ScopedSecretMinter
from mission_control.adapters.temporal.provider_lane_composition import compose_approval_broker
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.adapters.workspaces.git_workspaces import run_git
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.effects.ports import PullRequest
from mission_control.application.effects.repo_pr import RepoPullRequestExecutor
from mission_control.application.execution.approvals_governed import (
    GOVERNED_EFFECT_PERMISSION,
    GovernedEffectService,
    GovernedTool,
    GovernedToolPolicy,
    GovernedToolRegistry,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.application.execution.hosted_tools import HostedGovernedTools, HostedToolGate
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.application.secrets.broker import SecretBroker
from mission_control.bootstrap.signals import compose_signal_ingress
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.cursor_local import MemoryArtifacts
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.session_retention import RecordingDeletionScheduler
from tests.integration.anthropic_managed import test_session_lifecycle_live as lifecycle
from tests.integration.anthropic_managed.test_session_lifecycle_live import (
    ADDRESS,
    NAMESPACE,
    _cleanup,
    _frames,
    _lane_worker,
    _request,
    _run_record,
    _unit,
)
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_signal_ingress_postgres import ingress_login
from tests.unit.approvals.fixtures import answer

LIVE = (
    os.environ.get("MC_HL09_LIVE") == "1"
    and bool(os.environ.get("ANTHROPIC_API_KEY"))
    and float(os.environ.get("MC_PAID_BUDGET_USD", "0") or 0) >= 0.5
)
pytestmark = pytest.mark.skipif(
    not LIVE, reason="paid S2 opt-in requires MC_HL09_LIVE, API key and >=$0.50 cap"
)
DATE = "2026-10-14T00:00:00+0000"


class TrackedPrepare(ClaudeManagedPrepare):
    used = False

    async def sync(self, pack):
        self.used = True
        return await super().sync(pack)


class NoNetworkCredential:
    async def credential(self, repository):
        raise AssertionError("live drill publishes only to a temporary local bare remote")


class LocalPrFixture:
    def __init__(self):
        self.pr = None

    async def branch_head(self, repository, branch):
        return run_git("rev-parse", f"refs/heads/{branch}", cwd=Path(repository)).decode().strip()

    async def find_pull_request(self, repository, *, head, base):
        return self.pr

    async def create_pull_request(self, repository, *, head, base, title, body, draft):
        self.pr = PullRequest(
            number=1,
            url="https://fixture.invalid/hl09/pull/1",
            head_branch=head,
            head_sha=await self.branch_head(repository, head),
            base=base,
            draft=draft,
            state="open",
        )
        return self.pr


def local_base(root: Path) -> tuple[Path, str]:
    source, remote = root / "base", root / "remote.git"
    source.mkdir()
    remote.mkdir()
    run_git("init", "--quiet", "-b", "main", cwd=source)
    run_git("config", "user.name", "Mission Control Drill", cwd=source)
    run_git("config", "user.email", "drill@example.invalid", cwd=source)
    run_git("config", "core.autocrlf", "false", cwd=source)
    (source / "readme.txt").write_bytes(b"base\n")
    run_git("add", "readme.txt", cwd=source)
    run_git(
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "base",
        cwd=source,
        env={"GIT_AUTHOR_DATE": DATE, "GIT_COMMITTER_DATE": DATE},
    )
    base = run_git("rev-parse", "HEAD", cwd=source).decode().strip()
    run_git("init", "--bare", "--quiet", cwd=remote)
    run_git("push", "--quiet", str(remote), "main", cwd=source)
    return remote, base


def drill_pack(root: Path):
    directory = root / "pack"
    directory.mkdir()
    custom = [
        {"name": name, "description": description, "input_schema": schema}
        for name, description, schema in [
            (
                "mc_prepare",
                "Get the exact setup command. Call first.",
                {"type": "object", "properties": {}, "additionalProperties": False},
            ),
            (
                "mc_signal",
                "Report env.prepared after setup succeeds.",
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            ),
            (
                "mc_publish",
                "Publish the completed git bundle through Mission Control.",
                {
                    "type": "object",
                    "properties": {"branch": {"type": "string"}, "message": {"type": "string"}},
                    "required": ["branch", "message"],
                    "additionalProperties": False,
                },
            ),
        ]
    ]
    documents = {
        "pack.yaml": "schema: mc.hosted_pack.claude_managed.v1\npack:"
        " hl09-live\napplication: ai-engineer\nlane_profile:"
        " claude_managed\nplacement: cloud\ndata_class: internal\ntask_queue:"
        " mc-ai-engineer-lane-hosted\n",
        "agent.yaml": "name: mc-hl09-live\nmodel: claude-sonnet-5-5\nsystem:"
        " system.md\ntools:\n  bash: always_ask\ncustom_tools: " + json.dumps(custom) + "\n",
        "system.md": "This is an isolated Mission Control approval/publication"
        " drill. Use only the exact commands requested. Never access environment"
        " variables or credentials. Call mc_prepare first, execute its command"
        " exactly, then mc_signal env.prepared, then the requested code command,"
        " then mc_publish. Never create a PR yourself.\n",
        "environment.yaml": "kit: hl09-live\nnetworking:\n  allowed_hosts: []\n",
        "vault.yaml": "credentials: []\n",
    }
    for name, content in documents.items():
        (directory / name).write_text(content, "utf-8")
    return render_pack(load_pack(directory), installation_id="local")


@pytest.mark.common_db
async def test_live_approval_bundle_and_local_publication(
    common_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "LANE_QUEUE", f"hl09-live-lane-{uuid4().hex[:12]}")
    evidence = Path(os.environ["MC_HL09_EVIDENCE"])
    assert evidence.parent.is_dir(), "evidence destination must exist before provider provisioning"
    api = ManagedAgentsClient(SecretStr(os.environ["ANTHROPIC_API_KEY"]))
    pack = drill_pack(tmp_path)
    broker_secrets = SecretBroker(environment=WorkerEnvironmentSource({}))
    preparer = TrackedPrepare(
        api, broker_secrets, installation_id="local", labels={"mc_run": "run1-HL-09"}
    )
    deletions, artifacts = RecordingDeletionScheduler(), MemoryArtifacts()
    record: dict[str, Any] = {
        "model": "claude-sonnet-5-5",
        "vaults": 0,
        "network_hosts": [],
        "github_pr_live": False,
    }
    pool = await common_db.pool("mission_control_runtime")
    edge = await asyncpg.create_pool(await ingress_login(common_db), min_size=1, max_size=2)
    try:
        operation = await _unit(pool, common_db, pack, "placeholder")
        identity = LaneExecutionIdentity.of(operation, "claude_managed", 1)
        branch = mission_branch(identity.run_key, identity.activation_key)
        remote, base = local_base(tmp_path)
        setup = (
            "set -e; mkdir -p /tmp/mc-hl09; cd /tmp/mc-hl09; git init -q -b main; git"
            " config user.name 'Mission Control Drill'; git config user.email"
            " drill@example.invalid; git config core.autocrlf false; printf 'base\\n' >"
            " readme.txt; git add readme.txt; GIT_AUTHOR_DATE="
            + shlex.quote(DATE)
            + " GIT_COMMITTER_DATE="
            + shlex.quote(DATE)
            + " git -c commit.gpgsign=false commit -q -m base; git checkout -q -b "
            + shlex.quote(branch)
        )
        command = (
            "set -e; mkdir -p /mnt/session/outputs; cd /tmp/mc-hl09;"
            " printf 'live-provider-evidence\\n' >> readme.txt;"
            " git add readme.txt; git -c commit.gpgsign=false commit -q -m"
            " live-evidence; git bundle create /mnt/session/outputs/mc.bundle "
            + shlex.quote(branch)
        )
        prompt = (
            "Call mc_prepare and run its setup command byte-for-byte as bash, then call"
            " mc_signal with name env.prepared. Then run this exact bash command:\n"
            + command
            + "\nThen call mc_publish with branch "
            + branch
            + " and message HL09 live evidence. Wait for its result; then reply HL09-OK."
        )
        binding = ProviderExecutionBinding.sealed(
            **{
                **ProviderExecutionBinding.carried_by(operation).model_dump(
                    exclude={"binding_digest"}
                ),
                "repo_url": str(remote),
                "repo_ref": "main",
                "repo_commit": base,
            }
        )
        operation = OperationExecutionRequest.model_validate(
            {
                **operation.model_dump(mode="python"),
                **lane_fields(binding),
                "prompt_segments": [
                    {
                        **operation.prompt_segments[0].model_dump(),
                        "content": prompt,
                        "rendered_digest": sha256_digest(prompt),
                    }
                ],
            }
        )
        approval = compose_approval_broker(pool, connection_ref="hl09-live-worker")
        tasks = PostgresApprovalTaskRepository(pool)
        human = HumanTaskService(
            PostgresHumanTaskRepository(pool),
            request_scope=identity.request_scope,
            approvals=tasks,
            approval_wake=approval.hub,
        )
        gate = HostedToolGate(
            fences=PostgresStopFenceRepository(pool),
            intents=PostgresHookIntentLedger(pool),
            broker=approval,
            reviewers=("owner",),
            allowed_tools=frozenset({"bash", "mc_prepare", "mc_signal", "mc_publish"}),
            wait_seconds=10,
        )
        host = LocalPrFixture()
        publisher = GitBundlePublisher(tmp_path / "publication", NoNetworkCredential())

        def governed(op, execution):
            registry = GovernedToolRegistry(
                [
                    GovernedTool(
                        "mc_publish",
                        ManagedPublishExecutor(
                            client=api,
                            publisher=publisher,
                            host=host,
                            artifacts=artifacts,
                            operation=op,
                            identity=execution,
                        ),
                        GovernedToolPolicy(reviewers=("owner",)),
                        effect_kind="other",
                        family="repo",
                    ),
                    GovernedTool(
                        "repo_pr",
                        RepoPullRequestExecutor(host, artifacts),
                        GovernedToolPolicy(reviewers=("owner",)),
                        effect_kind="other",
                        family="repo",
                    ),
                ]
            )
            return GovernedEffectService(
                PostgresGovernedIntentRepository(pool),
                tasks,
                registry,
                request_scope=identity.request_scope,
                probe=PostgresApprovalContextProbe(pool),
                fences=PostgresStopFenceRepository(pool),
            )

        tools = ManagedTools(
            client=api,
            gate=gate,
            governed=HostedGovernedTools(
                governed,
                ActorContext(
                    actor_id="hl09-drill-runtime",
                    permissions=frozenset({GOVERNED_EFFECT_PERMISSION}),
                ),
                wait_seconds=300,
            ),
            signal=HostedSignalDelivery(
                compose_signal_ingress(
                    edge,
                    installation_id=common_db.installation_id,
                    application_id=common_db.application_id,
                ),
                ScopedSecretMinter(pool),
                broker_secrets.registry,
            ),
            setup_commands=(setup,),
            steady_tools=pack.agent_body([])["tools"],
            artifacts=artifacts,
            custody_wait_seconds=10,
        )
        harness = ClaudeManagedHarness(
            client=api,
            preparer=preparer,
            pack=pack,
            artifacts=artifacts,
            retention=SessionRetentionService(deletions),
            labels={"mc_run": "run1-HL-09"},
            tools=tools,
        )
        temporal = await Client.connect(ADDRESS, namespace=NAMESPACE)
        frames = PostgresFrameRepository(pool)
        resolutions = []

        async def review():
            while True:
                for task in await tasks.list_tasks(
                    identity.request_scope, run_id=identity.run_key, lifecycle="open"
                ):
                    await human.resolve(
                        task.human_task_id, answer(task), ActorContext(actor_id="owner")
                    )
                    resolutions.append(task.human_task_id)
                await asyncio.sleep(0.05)

        reviewer = asyncio.create_task(review())
        try:
            queue = f"hl09-live-wf-{uuid4().hex[:8]}"
            async with (
                Worker(
                    temporal,
                    task_queue=queue,
                    workflows=[OperationWorkflow],
                    workflow_runner=coordinator_workflow_runner(),
                ),
                _lane_worker(temporal, harness, operation, pool, frames),
            ):
                handle = await temporal.start_workflow(
                    OperationWorkflow.run,
                    _request(operation),
                    id=f"hl09-live-{uuid4().hex[:8]}",
                    task_queue=queue,
                    execution_timeout=timedelta(minutes=10),
                )
                result = await asyncio.wait_for(handle.result(), 600)
            record["run"] = _run_record(result, await _frames(frames, operation))
            record["human_task_resolutions"] = resolutions
            events = [event async for event in api.list_events(record["run"]["session"])]
            names = {event.get("id"): event.get("name") for event in events}
            results = []
            for event in events:
                if event.get("type") != "user.custom_tool_result":
                    continue
                diagnostic = {
                    "name": names.get(event.get("custom_tool_use_id")),
                    "is_error": bool(event.get("is_error")),
                }
                for block in event.get("content") or []:
                    try:
                        body = json.loads(block.get("text", ""))
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(body, dict):
                        diagnostic["result_keys"] = sorted(body)
                        for field in ("status", "required_action"):
                            value = body.get(field)
                            if isinstance(value, str) and value.replace("_", "").isalnum():
                                diagnostic[field] = value[:120]
                        code = body.get("error")
                        if isinstance(code, str) and code.replace("_", "").isalnum():
                            diagnostic["error_code"] = code[:120]
                results.append(diagnostic)
            record["tool_results"] = results
            output_files = await api.session_files(record["run"]["session"])
            record["post_turn_file_count"] = len(output_files)
            record["post_turn_bundle_count"] = sum(
                str(item.get("filename", "")).split("/")[-1] == "mc.bundle" for item in output_files
            )
            record["native_tool_results"] = [
                {
                    "name": names.get(event.get("tool_use_id")),
                    "is_error": bool(event.get("is_error")),
                }
                for event in events
                if event.get("type") == "agent.tool_result"
            ]
            record["native_tools"] = [
                {
                    "name": event.get("name"),
                    "input_keys": sorted(event.get("input") or {}),
                    "setup_exact": (event.get("input") or {}).get("command") == setup,
                    "setup_stripped": str((event.get("input") or {}).get("command", "")).strip()
                    == setup.strip(),
                    "permission": event.get("evaluated_permission"),
                }
                for event in events
                if event.get("type") == "agent.tool_use"
            ]
            record["confirmation_results"] = [
                {"name": names.get(event.get("tool_use_id")), "result": event.get("result")}
                for event in events
                if event.get("type") == "user.tool_confirmation"
            ]
            assert result.disposition == "completed" and host.pr is not None
            assert len(resolutions) >= 3, (
                "native bash approval, publication approval and repo_pr approval"
            )
            record["published_head"] = await host.branch_head(str(remote), branch)
            record["base_head"] = base
            record["fixture_pr_gateway"] = True
        finally:
            reviewer.cancel()
            await asyncio.gather(reviewer, return_exceptions=True)
    finally:
        if preparer.used:
            try:
                prepared = await preparer.sync(pack)
                for session in await api.list_sessions(agent_id=prepared.agent.agent_id):
                    sid = session["id"]
                    if session.get("status") == "running":
                        await api.send_events(sid, [{"type": "user.interrupt"}])
                        for _ in range(120):
                            if (await api.retrieve_session(sid)).get("status") == "idle":
                                break
                            await asyncio.sleep(1)
                    for file in await api.session_files(sid):
                        await api.delete_file(file["id"])
                    if not session.get("archived_at"):
                        await api.archive_session(sid)
            except Exception as error:
                record["file_cleanup_error"] = type(error).__name__
            finally:
                record["cleanup"] = await _cleanup(api, preparer, pack, deletions)
        else:
            record["cleanup"] = {"no_provider_resources": True, "spend_minor_units": 0}
        await asyncio.to_thread(
            evidence.write_text, json.dumps(record, indent=2, sort_keys=True), "utf-8"
        )
        await edge.close()
        await pool.close()
        await api.aclose()

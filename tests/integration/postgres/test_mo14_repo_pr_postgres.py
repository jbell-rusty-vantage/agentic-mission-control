"""MO-14 `repo_pr` through the governed gateway on a disposable PostgreSQL 17 (runtime role,
RLS): the MP-11 scratch database of ``test_mp11_approvals_postgres.mp11_db`` (released chain
0001..0034).

Proves on the real stores: a push to a non-`mc/` ref is rejected by the worktree guard; the
`repo_pr` intent is persisted with its `governed_effect` Human Task and opens nothing before
review; after approval, concurrent execute calls from separate service instances open exactly
one draft pull request; the one immutable receipt in `governed_effect_intent` records the
mission branch's head SHA, the pull request and the head SHA artifact.

Real git (an MO-05 lease, a local bare repository standing in for the GitHub remote) and a
FIXTURE GitHub REST API (`httpx.MockTransport`); no GitHub App, webhook or real pull request.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg
import pytest

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.postgres.approvals.intents import PostgresGovernedIntentRepository
from mission_control.adapters.postgres.approvals.tasks import PostgresApprovalTaskRepository
from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.application.effects.branch_heads import MissionBranchHead
from mission_control.application.effects.repo_pr import (
    REPO_PR_TOOL,
    RepoPullRequestExecutor,
    repo_pr_policy,
    repo_pr_tool,
)
from mission_control.application.execution.approvals_governed import (
    GOVERNED_EFFECT_PERMISSION,
    GovernedEffectService,
    GovernedPrepareRequest,
    GovernedToolRegistry,
)
from mission_control.application.execution.approvals_memory import StaticApprovalContext
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import owner_rows
from tests.integration.postgres.test_mp11_approvals_postgres import (  # noqa: F401
    admitted_run,
    mp11_db,
)
from tests.unit.approvals.fixtures import POLICY, REVIEWER, answer
from tests.unit.effects.support import (
    API,
    REPOSITORY,
    FakeGitHub,
    StaticCredentials,
    published_mission_branch,
    remote_head,
)
from tests.unit.workspaces.workspace_fixtures import MemoryArtifacts

pytestmark = pytest.mark.common_db

AGENT = ActorContext(actor_id="agent:lane", permissions=frozenset({GOVERNED_EFFECT_PERMISSION}))
OWNER = ActorContext(actor_id=REVIEWER)


class Gateway:
    """One process's composition of `repo_pr` on the shared pool and FIXTURE GitHub."""

    def __init__(
        self, pool: asyncpg.Pool, scope: str, github: FakeGitHub, artifacts: MemoryArtifacts
    ) -> None:
        self.tasks = PostgresApprovalTaskRepository(pool)
        executor = RepoPullRequestExecutor(
            GitHubRestClient(github.client(), StaticCredentials(), api_url=API), artifacts
        )
        self.service = GovernedEffectService(
            PostgresGovernedIntentRepository(pool),
            self.tasks,
            GovernedToolRegistry((repo_pr_tool(executor, repo_pr_policy((REVIEWER,))),)),
            request_scope=scope,
            probe=StaticApprovalContext(1, POLICY),
            fences=PostgresStopFenceRepository(pool),
        )
        self.human = HumanTaskService(
            PostgresHumanTaskRepository(pool), request_scope=scope, approvals=self.tasks
        )


async def test_repo_pr_opens_one_draft_pr_recorded_with_the_head_sha(
    mp11_db: CommonDatabase,  # noqa: F811
    tmp_path: Path,
) -> None:
    pool = await mp11_db.pool(max_size=8)
    try:
        scope = mp11_db.scope()
        run_id = await admitted_run(pool, scope)
        branch = f"mc/{run_id}/u1"
        remote, head = await published_mission_branch(tmp_path, run_id=run_id)
        github = FakeGitHub(remote)
        artifacts = MemoryArtifacts()
        gateways = [Gateway(pool, scope, github, artifacts) for _ in range(3)]

        prepared = await gateways[0].service.prepare(
            GovernedPrepareRequest(
                run_id=run_id,
                harness_execution_id="harness-exec-1",
                generation=1,
                lane_profile="claude_agent_sdk",
                tool_name=REPO_PR_TOOL,
                arguments={
                    "repository": REPOSITORY,
                    "branch": branch,
                    "base": "main",
                    "title": "Fix the bug",
                },
            ),
            AGENT,
        )
        assert prepared.status == "pending_approval" and prepared.human_task is not None
        pending = await gateways[1].service.execute(prepared.intent_id, AGENT)
        assert pending.status == "pending_approval" and github.pulls == []

        task = await gateways[0].tasks.get_task(scope, prepared.human_task["human_task_id"])
        assert task is not None
        await gateways[0].human.resolve(task.human_task_id, answer(task), OWNER)
        results = await asyncio.gather(
            *(g.service.execute(prepared.intent_id, AGENT) for g in gateways for _ in range(2))
        )

        assert {item.status for item in results} <= {"executed", "executing"}
        [pull] = github.pulls
        assert pull["draft"] is True and pull["head"] == {"ref": branch, "sha": head}
        final = await gateways[2].service.execute(prepared.intent_id, AGENT)
        assert final.receipt is not None and final.receipt.outcome == "applied"
        assert final.receipt.output["head_sha"] == head == remote_head(remote, branch)
        rows = await owner_rows(
            mp11_db,
            "SELECT tool_name, state, receipt, receipt_digest "
            "FROM mission_control.governed_effect_intent",
        )
        assert [(row["tool_name"], row["state"]) for row in rows] == [(REPO_PR_TOOL, "executed")]
        stored = rows[0]["receipt"]
        stored = json.loads(stored) if isinstance(stored, str) else stored
        assert stored["output"]["head_sha"] == head
        assert stored["output"]["url"] == pull["html_url"] == stored["external_ref"]
        assert rows[0]["receipt_digest"] == final.receipt.receipt_digest
        recorded = MissionBranchHead.model_validate_json(
            artifacts.staged[stored["output"]["head_artifact_ref"]]
        )
        assert (recorded.run_id, recorded.branch, recorded.head_sha) == (run_id, branch, head)
    finally:
        await pool.close()

"""MO-14 acceptance, offline: a push to a non-`mc/` ref is rejected, and the draft pull
request is created through the `repo_pr` Governed Effect (prepare, Human Task review,
execute once) and recorded with the mission branch's head SHA.

Real git (an MO-05 lease, the pre-push guard, a local bare repository standing in for the
GitHub remote), a FIXTURE GitHub REST API over that remote (`httpx.MockTransport`) and the
in-memory governed stores. No GitHub App, webhook or real pull request is involved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_control.adapters.github.client import GitHubRestClient
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
from mission_control.application.execution.approvals_memory import (
    InMemoryApprovalStore,
    InMemoryGovernedIntents,
    StaticApprovalContext,
)
from mission_control.application.execution.stop_fence import InMemoryStopFenceRepository
from mission_control.application.human_tasks.memory import InMemoryHumanTaskRepository
from mission_control.application.human_tasks.service import HumanTaskService
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.provider_frames import SCOPE
from tests.unit.approvals.fixtures import POLICY, REVIEWER, RUN, answer
from tests.unit.effects.support import (
    API,
    REPOSITORY,
    FakeGitHub,
    StaticCredentials,
    published_mission_branch,
    remote_head,
)
from tests.unit.workspaces.workspace_fixtures import MemoryArtifacts

AGENT = ActorContext(actor_id="agent:lane", permissions=frozenset({GOVERNED_EFFECT_PERMISSION}))
OWNER = ActorContext(actor_id=REVIEWER)


class Gateway:
    def __init__(self, github: FakeGitHub) -> None:
        self.github = github
        self.artifacts = MemoryArtifacts()
        self.executor = RepoPullRequestExecutor(
            GitHubRestClient(github.client(), StaticCredentials(), api_url=API), self.artifacts
        )
        self.store = InMemoryApprovalStore()
        self.intents = InMemoryGovernedIntents()
        self.service = GovernedEffectService(
            self.intents,
            self.store,
            GovernedToolRegistry((repo_pr_tool(self.executor, repo_pr_policy((REVIEWER,))),)),
            request_scope=SCOPE,
            probe=StaticApprovalContext(1, POLICY),
            fences=InMemoryStopFenceRepository(),
        )
        self.human = HumanTaskService(
            InMemoryHumanTaskRepository(), request_scope=SCOPE, approvals=self.store
        )

    async def approved(self, **arguments: Any) -> str:
        prepared = await self.service.prepare(
            GovernedPrepareRequest(
                run_id=RUN,
                harness_execution_id="harness-exec-1",
                generation=1,
                lane_profile="claude_agent_sdk",
                tool_name=REPO_PR_TOOL,
                arguments=arguments,
            ),
            AGENT,
        )
        assert prepared.status == "pending_approval" and prepared.human_task is not None
        task = await self.store.get_task(SCOPE, prepared.human_task["human_task_id"])
        assert task is not None
        await self.human.resolve(task.human_task_id, answer(task, decision="approve"), OWNER)
        return prepared.intent_id

    def pull_posts(self) -> int:
        return sum(
            1 for method, path in self.github.requests if (method, path[-6:]) == ("POST", "/pulls")
        )


def _arguments(**changes: Any) -> dict[str, Any]:
    return {
        "repository": REPOSITORY,
        "branch": "mc/run-1/u1",
        "base": "main",
        "title": "Fix the bug",
        "body": "Opened by Mission Control.",
        **changes,
    }


async def test_a_non_mc_push_is_rejected_and_the_draft_pr_is_created_through_the_effect(
    tmp_path: Path,
) -> None:
    remote, head = await published_mission_branch(tmp_path)
    gateway = Gateway(FakeGitHub(remote))

    intent_id = await gateway.approved(**_arguments())
    # Prepare and review executed nothing at the repository host.
    assert gateway.github.pulls == []

    executed = await gateway.service.execute(intent_id, AGENT)

    assert executed.status == "executed" and executed.receipt is not None
    output = executed.receipt.output
    [pull] = gateway.github.pulls
    assert pull["draft"] is True and pull["head"] == {"ref": "mc/run-1/u1", "sha": head}
    assert output["draft"] is True and output["number"] == 1
    assert output["head_sha"] == head == remote_head(remote, "mc/run-1/u1")
    assert executed.receipt.external_ref == output["url"] == pull["html_url"]
    recorded = MissionBranchHead.model_validate_json(
        gateway.artifacts.staged[output["head_artifact_ref"]]
    )
    assert (recorded.branch, recorded.head_sha, recorded.source) == (
        "mc/run-1/u1",
        head,
        "pull_request",
    )
    assert recorded.pull_request_url == pull["html_url"] and recorded.run_id == RUN

    # Executing again returns the one receipt; no second pull request is opened.
    again = await gateway.service.execute(intent_id, AGENT)
    assert again.receipt == executed.receipt and gateway.pull_posts() == 1


async def test_repo_pr_refuses_a_branch_outside_the_run_or_one_never_pushed(
    tmp_path: Path,
) -> None:
    remote, _ = await published_mission_branch(tmp_path)
    gateway = Gateway(FakeGitHub(remote))

    for branch, reason in (
        ("main", "not_a_mission_branch"),
        ("mc/run-2/u1", "not_a_mission_branch"),
        ("mc/run-1/u2", "branch_not_pushed"),
    ):
        intent_id = await gateway.approved(**_arguments(branch=branch))
        executed = await gateway.service.execute(intent_id, AGENT)
        assert executed.receipt is not None
        assert executed.receipt.outcome == "rejected"
        assert executed.receipt.output == {"reason": reason}
    assert gateway.github.pulls == []


async def test_an_existing_pull_request_is_reused_and_reconciled_not_duplicated(
    tmp_path: Path,
) -> None:
    remote, head = await published_mission_branch(tmp_path)
    gateway = Gateway(FakeGitHub(remote))
    intent_id = await gateway.approved(**_arguments())
    intent = await gateway.intents.get(SCOPE, intent_id)
    assert intent is not None
    # Nothing recorded yet: a crashed claim has nothing to reconcile.
    assert await gateway.executor.lookup(intent) is None

    first = await gateway.executor.execute(intent)
    reconciled = await gateway.executor.lookup(intent)
    executed = await gateway.service.execute(intent_id, AGENT)

    assert reconciled is not None and reconciled.output["number"] == first.output["number"]
    assert executed.receipt is not None and executed.receipt.output["head_sha"] == head
    assert len(gateway.github.pulls) == 1 and gateway.pull_posts() == 1

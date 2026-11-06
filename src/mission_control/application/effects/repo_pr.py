"""The `repo_pr` Governed Effect: Mission Control opens a mission branch's pull request
(SPEC-01 section 6; MO-14).

The agent never opens the pull request. It asks for one through the governed gateway
(prepare, review as a Human Task, execute once), so approval and recording stay in Mission
Control. Executing the bound intent:

1. refuses a branch that is not a mission branch of the intent's run (`mc/{run}/...`);
2. reads the branch head at the repository host and refuses a branch that was never pushed;
3. reuses the pull request already open from that branch into the base, or creates it (a
   draft unless the arguments say otherwise), so a retried or reconciled intent never opens
   a second one;
4. records the head the pull request points at as a `mc.mission_branch_head.v1` artifact and
   returns its number, URL, head SHA and artifact ref for the one immutable receipt.

`lookup` is the reconciliation of a claim left by a crashed caller: the pull request from
the branch is the domain record of the effect.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mission_control.application.effects.branch_heads import (
    HeadArtifactSink,
    MissionBranchHead,
    record_branch_head,
)
from mission_control.application.effects.mission_branches import is_mission_branch
from mission_control.application.effects.ports import PullRequest, RepositoryHost
from mission_control.application.execution.approvals_governed import (
    GovernedEffectResult,
    GovernedIntent,
    GovernedTool,
    GovernedToolPolicy,
)

REPO_PR_TOOL: Final = "repo_pr"
REPO_EFFECT_FAMILY: Final = "repo"
DEFAULT_PROMPT: Final = "Open this pull request from the mission branch?"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RepoPullRequestArguments(BaseModel):
    """The reviewed arguments of one `repo_pr` intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = Field(min_length=1, max_length=2_048)
    branch: str = Field(min_length=1, max_length=256)
    base: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=65_536)
    draft: bool = True


def _rejected(reason: str) -> GovernedEffectResult:
    return GovernedEffectResult(outcome="rejected", output={"reason": reason})


class RepoPullRequestExecutor:
    """`ReconcilingGovernedExecutor` of `repo_pr` over a repository host."""

    def __init__(
        self,
        host: RepositoryHost,
        artifacts: HeadArtifactSink,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._host = host
        self._artifacts = artifacts
        self._clock = clock

    async def execute(self, intent: GovernedIntent) -> GovernedEffectResult:
        try:
            arguments = RepoPullRequestArguments.model_validate(intent.arguments)
        except ValidationError:
            return _rejected("invalid_arguments")
        if not is_mission_branch(arguments.branch, intent.run_id):
            return _rejected("not_a_mission_branch")
        head = await self._host.branch_head(arguments.repository, arguments.branch)
        if head is None:
            return _rejected("branch_not_pushed")
        pull_request = await self._host.find_pull_request(
            arguments.repository, head=arguments.branch, base=arguments.base
        )
        if pull_request is None:
            pull_request = await self._host.create_pull_request(
                arguments.repository,
                head=arguments.branch,
                base=arguments.base,
                title=arguments.title,
                body=arguments.body,
                draft=arguments.draft,
            )
        return await self._applied(intent, arguments, pull_request)

    async def lookup(self, intent: GovernedIntent) -> GovernedEffectResult | None:
        try:
            arguments = RepoPullRequestArguments.model_validate(intent.arguments)
        except ValidationError:
            return None
        pull_request = await self._host.find_pull_request(
            arguments.repository, head=arguments.branch, base=arguments.base
        )
        if pull_request is None:
            return None
        return await self._applied(intent, arguments, pull_request)

    async def _applied(
        self,
        intent: GovernedIntent,
        arguments: RepoPullRequestArguments,
        pull_request: PullRequest,
    ) -> GovernedEffectResult:
        head_ref = await record_branch_head(
            self._artifacts,
            MissionBranchHead(
                run_id=intent.run_id,
                lane_profile=intent.lane_profile,
                repository=arguments.repository,
                branch=pull_request.head_branch,
                head_sha=pull_request.head_sha,
                source="pull_request",
                pull_request_url=pull_request.url,
                observed_at=self._clock(),
            ),
            request_scope=intent.request_scope,
        )
        return GovernedEffectResult(
            outcome="applied",
            output={
                "repository": arguments.repository,
                "branch": pull_request.head_branch,
                "base": pull_request.base,
                "number": pull_request.number,
                "url": pull_request.url,
                "draft": pull_request.draft,
                "state": pull_request.state,
                "head_sha": pull_request.head_sha,
                "head_artifact_ref": head_ref,
            },
            external_ref=pull_request.url,
        )


def repo_pr_policy(reviewers: Sequence[str], *, prompt: str = DEFAULT_PROMPT) -> GovernedToolPolicy:
    """`repo_pr` always asks a human: the reviewers approve each pull request intent."""

    return GovernedToolPolicy(requires_approval=True, reviewers=tuple(reviewers), prompt=prompt)


def repo_pr_tool(executor: RepoPullRequestExecutor, policy: GovernedToolPolicy) -> GovernedTool:
    """The `repo_pr` tool for a `GovernedToolRegistry`; `policy` names its reviewers."""

    return GovernedTool(
        name=REPO_PR_TOOL,
        executor=executor,
        policy=policy,
        effect_kind="other",
        family=REPO_EFFECT_FAMILY,
    )


__all__ = [
    "DEFAULT_PROMPT",
    "REPO_EFFECT_FAMILY",
    "REPO_PR_TOOL",
    "RepoPullRequestArguments",
    "RepoPullRequestExecutor",
    "repo_pr_policy",
    "repo_pr_tool",
]

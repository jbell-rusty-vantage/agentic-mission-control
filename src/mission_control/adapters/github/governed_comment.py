"""Comments are scoped to the PR of this mission branch, with durable intent markers."""

from __future__ import annotations

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.remote_session.function_custody import admitted
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.effects.ports import PullRequest
from mission_control.application.execution.approvals_governed import (
    GovernedEffectResult,
    GovernedIntent,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest


class MissionPrCommentExecutor:
    def __init__(
        self,
        host: GitHubRestClient,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
    ) -> None:
        self.host, self.operation, self.identity = host, operation, identity

    async def _target(self, intent: GovernedIntent) -> PullRequest | None:
        binding = ProviderExecutionBinding.carried_by(self.operation)
        if (
            binding is None
            or not binding.repo_url
            or not binding.repo_ref
            or not admitted(intent, self.identity)
            or intent.arguments.get("repository") != binding.repo_url
            or intent.arguments.get("branch")
            != mission_branch(self.identity.run_key, self.identity.activation_key)
            or intent.arguments.get("base") != binding.repo_ref
        ):
            return None
        return await self.host.find_pull_request(
            binding.repo_url, head=intent.arguments["branch"], base=binding.repo_ref
        )

    async def lookup(self, intent: GovernedIntent) -> GovernedEffectResult | None:
        target = await self._target(intent)
        if target is None:
            return None
        marker = f"<!-- mission-control-intent:{intent.intent_id} -->"
        url = await self.host.find_comment(intent.arguments["repository"], target.number, marker)
        return GovernedEffectResult(outcome="noop", external_ref=url) if url else None

    async def execute(self, intent: GovernedIntent) -> GovernedEffectResult:
        target = await self._target(intent)
        if target is None:
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "mission_pr_not_in_custody"}
            )
        previous = await self.lookup(intent)
        if previous:
            return previous
        body = (
            str(intent.arguments.get("body") or "")
            + f"\n\n<!-- mission-control-intent:{intent.intent_id} -->"
        )
        url = await self.host.create_comment(intent.arguments["repository"], target.number, body)
        return GovernedEffectResult(outcome="applied", external_ref=url)

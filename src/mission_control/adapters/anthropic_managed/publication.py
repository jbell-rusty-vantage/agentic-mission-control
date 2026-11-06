"""The governed mc_publish executor: session-scoped file custody and verified bundle push."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.cursor.local import LaneArtifactSink
from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.effects.ports import RepositoryHost
from mission_control.application.execution.approvals_governed import (
    GovernedEffectResult,
    GovernedIntent,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest


class ManagedPublishExecutor:
    """Scoped to the admitted operation, never to repository arguments supplied by a tool."""

    def __init__(
        self,
        *,
        client: ManagedAgentsClient,
        publisher: GitBundlePublisher,
        host: RepositoryHost,
        artifacts: LaneArtifactSink,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        secret_values: Iterable[str] = (),
    ) -> None:
        self._client, self._publisher, self._host, self._artifacts = (
            client,
            publisher,
            host,
            artifacts,
        )
        self._operation, self._identity = operation, identity
        self._secrets = tuple(secret_values)

    def _admitted(self, intent: GovernedIntent) -> bool:
        binding = ProviderExecutionBinding.carried_by(self._operation)
        args = intent.arguments
        return bool(
            binding is not None
            and intent.request_scope == self._identity.request_scope
            and intent.run_id == self._identity.run_key
            and intent.harness_execution_id == str(self._identity.harness_execution_id)
            and intent.generation == self._identity.attempt_no
            and args.get("repository") == binding.repo_url
            and args.get("base_commit") == binding.repo_commit
            and args.get("branch")
            == mission_branch(self._identity.run_key, self._identity.activation_key)
        )

    async def _bundle(self, args: dict[str, Any]) -> bytes | None:
        session_id, file_id = str(args.get("session_id") or ""), str(args.get("file_id") or "")
        if not session_id or not file_id:
            return None
        files = await self._client.session_files(session_id)
        if not any(item.get("id") == file_id for item in files):
            return None  # A Files API id from another session is not publication custody.
        content = await self._client.download_file(file_id)
        if f"sha256:{sha256(content).hexdigest()}" != args.get("bundle_digest"):
            return None
        return content

    async def execute(self, intent: GovernedIntent) -> GovernedEffectResult:
        if not self._admitted(intent):
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "publication_binding_mismatch"}
            )
        content = await self._bundle(intent.arguments)
        if content is None:
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "publication_bundle_not_in_custody"}
            )
        artifact = await self._artifacts.stage(
            request_scope=intent.request_scope,
            name=f"hosted-publication/{intent.intent_id}/commits.bundle",
            content=content,
            media_type="application/x-git-bundle",
        )
        args = intent.arguments
        head = await self._publisher.publish(
            repository=args["repository"],
            run_id=intent.run_id,
            branch=args["branch"],
            base_commit=args["base_commit"],
            bundle=content,
            secret_values=self._secrets,
        )
        return GovernedEffectResult(
            outcome="applied",
            output={
                "branch": args["branch"],
                "head_sha": head,
                "bundle_ref": artifact,
                "bundle_digest": args["bundle_digest"],
            },
        )

    async def lookup(self, intent: GovernedIntent) -> GovernedEffectResult | None:
        if not self._admitted(intent):
            return None
        content = await self._bundle(intent.arguments)
        if content is None:
            return None
        branch = intent.arguments["branch"]
        # Immutable bundle header identifies the requested commit for reconciliation.
        # Execution still verifies pack objects, ancestry and every commit before pushing.
        header = content.split(b"\n\n", 1)[0]
        if len(header) > 65_536:
            return None
        advertised = [
            line.split(maxsplit=1)
            for line in header.splitlines()
            if line.endswith(f" refs/heads/{branch}".encode())
        ]
        if len(advertised) != 1:
            return None
        head = advertised[0][0].decode("ascii", "strict")
        if await self._host.branch_head(intent.arguments["repository"], branch) != head:
            return None
        artifact = await self._artifacts.stage(
            request_scope=intent.request_scope,
            name=f"hosted-publication/{intent.intent_id}/commits.bundle",
            content=content,
            media_type="application/x-git-bundle",
        )
        return GovernedEffectResult(
            outcome="noop",
            output={
                "branch": branch,
                "head_sha": head,
                "bundle_digest": intent.arguments["bundle_digest"],
                "bundle_ref": artifact,
            },
        )

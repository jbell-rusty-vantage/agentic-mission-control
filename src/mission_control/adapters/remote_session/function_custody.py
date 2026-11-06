"""Trusted artifact custody for function calls and scoped git bundle publication."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from mission_control.adapters.cursor.local import LaneArtifactSink
from mission_control.adapters.workspaces.bundle_publication import GitBundlePublisher
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.effects.ports import RepositoryHost
from mission_control.application.execution.approvals_governed import (
    GovernedEffectResult,
    GovernedIntent,
    GovernedIntentRepository,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest


class ArtifactCustody(LaneArtifactSink, Protocol):
    async def retrieve(self, durable_ref: str) -> bytes: ...


def admitted(intent: GovernedIntent, identity: LaneExecutionIdentity) -> bool:
    return (
        intent.request_scope == identity.request_scope
        and intent.run_id == identity.run_key
        and intent.harness_execution_id == str(identity.harness_execution_id)
        and intent.generation == identity.attempt_no
    )


class HostedArtifactUploadExecutor:
    def __init__(self, artifacts: ArtifactCustody, identity: LaneExecutionIdentity) -> None:
        self.artifacts, self.identity = artifacts, identity

    async def execute(self, intent: GovernedIntent) -> GovernedEffectResult:
        args = intent.arguments
        if not admitted(intent, self.identity):
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "artifact_scope_mismatch"}
            )
        content = await self.artifacts.retrieve(str(args["artifact_ref"]))
        if (
            len(content) > 8 * 1024 * 1024
            or "sha256:" + sha256(content).hexdigest() != args["content_digest"]
        ):
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "artifact_digest_mismatch"}
            )
        expected = await self.artifacts.stage(
            request_scope=intent.request_scope,
            name=str(args["custody_name"]),
            content=content,
            media_type=str(args["media_type"]),
        )
        if expected != args["artifact_ref"]:
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "artifact_scope_mismatch"}
            )
        return GovernedEffectResult(
            outcome="applied",
            output={
                key: args[key]
                for key in (
                    "artifact_ref",
                    "content_digest",
                    "session_id",
                    "turn_id",
                    "path",
                    "media_type",
                )
            },
        )

    async def lookup(self, intent: GovernedIntent) -> GovernedEffectResult | None:
        # Custody is content addressed and scoped; repeat verification is idempotent.
        result = await self.execute(intent)
        return result if result.outcome == "applied" else None


class CustodiedBundlePublishExecutor:
    def __init__(
        self,
        *,
        artifacts: ArtifactCustody,
        intents: GovernedIntentRepository,
        publisher: GitBundlePublisher,
        host: RepositoryHost,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self.artifacts, self.intents, self.publisher, self.host = (
            artifacts,
            intents,
            publisher,
            host,
        )
        self.operation, self.identity, self.secrets = operation, identity, secret_values

    async def _bundle(self, intent: GovernedIntent) -> tuple[bytes, GovernedIntent] | None:
        binding, args = ProviderExecutionBinding.carried_by(self.operation), intent.arguments
        if (
            binding is None
            or not admitted(intent, self.identity)
            or args.get("repository") != binding.repo_url
            or args.get("base_commit") != binding.repo_commit
            or args.get("branch")
            != mission_branch(self.identity.run_key, self.identity.activation_key)
        ):
            return None
        upload = await self.intents.get(
            intent.request_scope, str(args.get("upload_intent_id") or "")
        )
        if (
            upload is None
            or not admitted(upload, self.identity)
            or upload.tool_name != "mc_upload_artifact"
            or upload.receipt is None
            or upload.receipt.outcome not in {"applied", "noop"}
            or upload.receipt.output.get("session_id") != args.get("session_id")
            or upload.receipt.output.get("path") != "/workspace/outputs/mc.bundle"
        ):
            return None
        content = await self.artifacts.retrieve(upload.receipt.output["artifact_ref"])
        if "sha256:" + sha256(content).hexdigest() != upload.receipt.output["content_digest"]:
            return None
        return content, upload

    async def execute(self, intent: GovernedIntent) -> GovernedEffectResult:
        stored = await self._bundle(intent)
        if stored is None:
            return GovernedEffectResult(
                outcome="rejected", output={"reason": "bundle_not_in_scoped_custody"}
            )
        content, upload = stored
        assert upload.receipt is not None
        args = intent.arguments
        head = await self.publisher.publish(
            repository=args["repository"],
            run_id=intent.run_id,
            branch=args["branch"],
            base_commit=args["base_commit"],
            bundle=content,
            secret_values=self.secrets,
        )
        return GovernedEffectResult(
            outcome="applied",
            output={
                "head_sha": head,
                "branch": args["branch"],
                "bundle_ref": upload.receipt.output["artifact_ref"],
                "bundle_digest": upload.receipt.output["content_digest"],
            },
        )

    async def lookup(self, intent: GovernedIntent) -> GovernedEffectResult | None:
        stored = await self._bundle(intent)
        if stored is None:
            return None
        content, upload = stored
        assert upload.receipt is not None
        branch = intent.arguments["branch"]
        advertised = [
            line.split(maxsplit=1)
            for line in content.split(b"\n\n", 1)[0].splitlines()
            if line.endswith(f" refs/heads/{branch}".encode())
        ]
        if len(advertised) != 1:
            return None
        head = advertised[0][0].decode("ascii", "strict")
        if await self.host.branch_head(intent.arguments["repository"], branch) != head:
            return None
        return GovernedEffectResult(
            outcome="noop",
            output={
                "head_sha": head,
                "branch": branch,
                "bundle_ref": upload.receipt.output["artifact_ref"],
                "bundle_digest": upload.receipt.output["content_digest"],
            },
        )

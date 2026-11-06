"""Root-turn Agents API function calls through durable effects and scoped artifact custody."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.remote_session.function_custody import ArtifactCustody
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.execution.approvals_governed import GovernedRejected
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.hosted_tools import (
    HostedCall,
    HostedGovernedTools,
    HostedSignal,
    HostedToolGate,
)
from mission_control.application.secrets.redaction import SecretValueRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest


def object_value(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, Mapping) else {}


class AgentsTools:
    def __init__(
        self,
        *,
        client: AgentsApiClient,
        gate: HostedToolGate,
        governed: HostedGovernedTools,
        signal: HostedSignal,
        artifacts: ArtifactCustody,
        secrets: SecretValueRegistry,
        setup_commands: Callable[
            [OperationExecutionRequest, LaneExecutionIdentity], Awaitable[tuple[str, ...]]
        ]
        | None = None,
    ) -> None:
        self.client, self.gate, self.governed = client, gate, governed
        self.signal, self.artifacts, self.secrets = signal, artifacts, secrets
        self.setup_commands = setup_commands

    async def answer_pending(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        session_id: str,
        turn_id: str,
    ) -> None:
        state = await self.client.retrieve_session(session_id)
        if state.get("status") != "requires_action":
            return
        for action in state.get("required_actions") or []:
            if (
                not isinstance(action, Mapping)
                or action.get("type") != "function_call"
                or action.get("turn_id") != turn_id
                or not action.get("call_id")
            ):
                continue
            arguments = action.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = None
            call = HostedCall(
                session_id,
                turn_id,
                str(action["call_id"]),
                str(action.get("name") or ""),
                dict(arguments) if isinstance(arguments, Mapping) else {},
            )
            result: dict[str, Any] | None
            if not await self.gate.admit(operation, identity, call):
                result = {"error": "effect_not_admitted"}
            elif not isinstance(arguments, Mapping):
                result = {"error": "invalid_arguments"}
            else:
                try:
                    result = await self._execute(operation, identity, call)
                except (GovernedRejected, ValueError) as error:
                    result = {
                        "error": error.code
                        if isinstance(error, GovernedRejected)
                        else "invalid_tool_request"
                    }
            if result is None:
                continue  # provider request and Human Task remain pending, including timeout
            # Re-read pending handles before submission. No stale or subagent handle is answered.
            fresh = await self.client.retrieve_session(session_id)
            if not any(
                item.get("type") == "function_call"
                and item.get("call_id") == call.call_id
                and item.get("turn_id") == turn_id
                for item in fresh.get("required_actions", [])
            ):
                continue
            success = "error" not in result
            event = {
                "type": "agent.session.input.tool_result",
                "call_id": call.call_id,
                "turn_id": turn_id,
                "success": success,
                **(
                    {"output": json.dumps(result, sort_keys=True)}
                    if success
                    else {"error": str(result["error"])}
                ),
            }
            await self.client.send_events(
                session_id, [event], idempotency_key="mc-tool:" + call.native_ref
            )

    async def _execute(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
    ) -> dict[str, Any] | None:
        commands = (
            await self.setup_commands(operation, identity)
            if self.setup_commands is not None
            else ()
        )
        provider = ProviderExecutionBinding.carried_by(operation)
        preparation_digest = (
            "sha256:"
            + sha256(
                json.dumps(
                    {
                        "binding": operation.effective_configuration_digest,
                        "provider_binding": provider.binding_digest if provider else None,
                        "commands": commands,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
        )
        if call.name == "mc_prepare":
            return {
                "preparation_digest": preparation_digest,
                "commands": list(commands),
                "workspace": "/workspace/repo",
                "signal_after": "env.prepared",
            }
        if self.setup_commands is not None:
            items = [
                item async for item in self.client.items(call.session_id, turn_id=call.turn_id)
            ]
            prepared_calls = {
                str(item.get("call_id"))
                for item in items
                if item.get("type") == "function_call"
                and item.get("name") == "mc_signal"
                and object_value(item.get("arguments")).get("name") == "env.prepared"
            }
            ready = any(
                item.get("type") == "function_call_output"
                and str(item.get("call_id")) in prepared_calls
                and object_value(item.get("output")).get("status") == "recorded"
                for item in items
            )
            if not ready:
                async for turn in self.client.turns(call.session_id):
                    if (
                        turn.get("id") == call.turn_id
                        or turn.get("subagent_id") is not None
                        or turn.get("status") != "completed"
                    ):
                        continue
                    previous = [
                        item
                        async for item in self.client.items(
                            call.session_id, turn_id=str(turn["id"])
                        )
                        if item.get("subagent_id") is None
                        and item.get("turn_id", turn["id"]) == turn["id"]
                    ]
                    previous_offered = {
                        str(item.get("call_id"))
                        for item in previous
                        if item.get("type") == "function_call" and item.get("name") == "mc_prepare"
                    }
                    sealed = any(
                        item.get("type") == "function_call_output"
                        and str(item.get("call_id")) in previous_offered
                        and object_value(item.get("output")).get("preparation_digest")
                        == preparation_digest
                        for item in previous
                    )
                    completed = {
                        item.get("command")
                        for item in previous
                        if item.get("type") == "command_execution"
                        and item.get("status") == "completed"
                        and item.get("exit_code") == 0
                        and isinstance(item.get("command"), str)
                    }
                    signals = {
                        str(item.get("call_id"))
                        for item in previous
                        if item.get("type") == "function_call"
                        and item.get("name") == "mc_signal"
                        and object_value(item.get("arguments")).get("name") == "env.prepared"
                    }
                    if (
                        sealed
                        and set(commands) <= completed
                        and any(
                            item.get("type") == "function_call_output"
                            and str(item.get("call_id")) in signals
                            and object_value(item.get("output")).get("status") == "recorded"
                            for item in previous
                        )
                    ):
                        ready = True
                        break
            if call.name == "mc_signal" and call.arguments.get("name") == "env.prepared":
                offered = any(
                    item.get("type") == "function_call" and item.get("name") == "mc_prepare"
                    for item in items
                )
                completed = {
                    item.get("command")
                    for item in items
                    if item.get("type") == "command_execution"
                    and item.get("status") == "completed"
                    and item.get("exit_code") == 0
                    and isinstance(item.get("command"), str)
                }
                if not offered or not set(commands) <= completed:
                    return {"error": "mission_layer_not_completed"}
            elif (
                call.name not in {"mc_request_approval", "mc_record_intent", "mc_signal"}
                and not ready
            ):
                return {"error": "environment_not_prepared"}
        if call.name == "mc_signal":
            result = await self.signal(identity, call)
            return (
                result
                if "error" in result
                else {"signal_id": call.native_ref, "status": "recorded"}
            )
        if call.name == "mc_record_intent":
            return {"intent_ref": call.native_ref}
        if call.name == "mc_request_approval":
            return await self.gate.permission(operation, identity, call)
        if call.name == "mc_upload_artifact":
            return await self._upload(operation, identity, call)
        binding = ProviderExecutionBinding.carried_by(operation)
        if (
            binding is None
            or not binding.repo_url
            or not binding.repo_ref
            or not binding.repo_commit
        ):
            return {"error": "tool_requires_bound_repository"}
        branch = mission_branch(identity.run_key, identity.activation_key)
        if call.name == "mc_publish":
            if call.arguments.get("branch", branch) != branch:
                return {"error": "publication_branch_not_admitted"}
            arguments = {
                "repository": binding.repo_url,
                "base_commit": binding.repo_commit,
                "branch": branch,
                "session_id": call.session_id,
                "upload_intent_id": call.arguments.get("upload_intent_id"),
            }
            return await self.governed.execute(
                operation,
                identity,
                HostedCall(call.session_id, call.turn_id, call.call_id, call.name, arguments),
            )
        if call.name in {"mc_open_pr", "mc_comment"}:
            message = str(call.arguments.get("message") or call.arguments.get("body") or "")
            if self.secrets.redact(message) != message:
                return {"error": "secret_in_effect_payload"}
            arguments = {
                "repository": binding.repo_url,
                "branch": branch,
                "base": binding.repo_ref,
                "title": str(call.arguments.get("title") or "Mission results")[:256],
                "body": message,
                "draft": True,
            }
            return await self.governed.execute(
                operation,
                identity,
                HostedCall(call.session_id, call.turn_id, call.call_id, call.name, arguments),
                tool_name="repo_pr" if call.name == "mc_open_pr" else "mc_comment",
            )
        return {"error": "unsupported_function"}

    async def _upload(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
    ) -> dict[str, Any] | None:
        path = str(call.arguments.get("path") or "")
        normalized = PurePosixPath(path)
        if (
            not path.startswith("/workspace/outputs/")
            or ".." in normalized.parts
            or str(normalized) != path
            or normalized.name == ".env"
            or ".scratch" in normalized.parts
        ):
            return {"error": "artifact_path_not_admitted"}
        encoded = call.arguments.get("content_base64")
        if encoded is not None:
            if not isinstance(encoded, str) or len(encoded) > 12 * 1024 * 1024:
                return {"error": "artifact_size_exceeded"}
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                return {"error": "invalid_artifact_encoding"}
        else:
            candidates = [
                item
                async for item in self.client.artifacts(call.session_id)
                if item.get("session_id") == call.session_id and item.get("path") == path
            ]
            if len(candidates) != 1:
                return {
                    "error": "artifact_not_published",
                    "required_action": "complete_turn_or_send_bounded_content_base64",
                }
            content = await self.client.artifact_content(call.session_id, str(candidates[0]["id"]))
        if len(content) > 8 * 1024 * 1024:
            return {"error": "artifact_size_exceeded"}
        text = content.decode("utf-8", "replace")
        if self.secrets.redact(text) != text:
            return {"error": "secret_in_artifact"}
        digest = "sha256:" + sha256(content).hexdigest()
        name = "hosted-upload/" + call.native_ref.removeprefix("sha256:") + "/" + normalized.name
        media = (
            "application/x-git-bundle"
            if normalized.name == "mc.bundle"
            else "application/octet-stream"
        )
        reference = await self.artifacts.stage(
            request_scope=identity.request_scope, name=name, content=content, media_type=media
        )
        args = {
            "artifact_ref": reference,
            "content_digest": digest,
            "custody_name": name,
            "path": path,
            "session_id": call.session_id,
            "turn_id": call.turn_id,
            "media_type": media,
        }
        return await self.governed.execute(
            operation,
            identity,
            HostedCall(call.session_id, call.turn_id, call.call_id, call.name, args),
        )

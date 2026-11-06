"""Managed Agents permission confirmations, preamble and Mission Control custom tools.

The provider holds requests durably. We answer only ids in its requires_action
idle, after the shared Stop Fence/Operation Intent gate; no pending Human Task is
silently approved on a timeout or on replay.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.cursor.local import LaneArtifactSink
from mission_control.application.effects.mission_branches import mission_branch
from mission_control.application.execution.approvals_governed import GovernedRejected
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.hosted_tools import (
    HostedCall,
    HostedGovernedTools,
    HostedSignal,
    HostedToolGate,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.stop_fence import EffectKind


@dataclass
class _Preparation:
    offered: bool = False
    completed: set[str] = field(default_factory=set)
    ready: bool = False


class ManagedTools:
    def __init__(
        self,
        *,
        client: ManagedAgentsClient,
        gate: HostedToolGate,
        governed: HostedGovernedTools,
        signal: HostedSignal,
        setup_commands: Sequence[str] = (),
        steady_tools: Sequence[Mapping[str, Any]] = (),
        artifacts: LaneArtifactSink | None = None,
        custody_wait_seconds: float = 0,
    ) -> None:
        self._client, self._gate, self._governed, self._signal = client, gate, governed, signal
        self._commands = tuple(setup_commands)
        self._steady_tools = tuple(dict(tool) for tool in steady_tools)
        self._artifacts = artifacts
        if not 0 <= custody_wait_seconds <= 30:
            raise ValueError("file custody wait must be between zero and 30 seconds")
        self._custody_wait = custody_wait_seconds
        if not self._steady_tools:
            raise ValueError("managed readiness requires the complete steady-state tool projection")

    async def answer_pending(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        session_id: str,
        turn_id: str,
        idle: Mapping[str, Any],
    ) -> None:
        reason = idle.get("stop_reason")
        if not isinstance(reason, Mapping) or reason.get("type") != "requires_action":
            return
        state = await self._client.retrieve_session(session_id)
        if state.get("status") != "idle":
            return
        events = [event async for event in self._client.list_events(session_id)]
        by_id = {str(event["id"]): event for event in events if event.get("id")}
        preparation = self._restore(events)
        answered = {
            str(event.get("custom_tool_use_id") or event.get("tool_use_id"))
            for event in events
            if event.get("type") in {"user.custom_tool_result", "user.tool_confirmation"}
        }
        pending_ids = sorted(
            reason.get("event_ids") or [],
            key=lambda key: (
                0
                if by_id.get(str(key), {}).get("type") in {"agent.tool_use", "agent.mcp_tool_use"}
                else 1
            ),
        )
        for pending in pending_ids:
            call_id = str(pending)
            event = by_id.get(call_id)
            if event is None or call_id in answered:
                continue
            name = str(event.get("name") or "")
            arguments = event.get("input")
            call = HostedCall(
                session_id,
                turn_id,
                call_id,
                name,
                dict(arguments) if isinstance(arguments, Mapping) else {},
            )
            kind: EffectKind = (
                "shell" if name == "bash" else "file" if name in {"write", "edit"} else "other"
            )
            if event.get("type") in {"agent.tool_use", "agent.mcp_tool_use"}:
                answer = await self._permission(operation, identity, call, preparation, kind)
                if answer is not None:
                    await self._client.send_events(
                        session_id,
                        [{"type": "user.tool_confirmation", "tool_use_id": call_id, **answer}],
                    )
            elif event.get("type") == "agent.custom_tool_use":
                result = await self._custom(operation, identity, call, preparation)
                if result is not None:
                    if not await self._gate.admit(operation, identity, call):
                        result = {"error": "STOP_FENCED"}
                    await self._client.send_events(
                        session_id,
                        [
                            {
                                "type": "user.custom_tool_result",
                                "custom_tool_use_id": call_id,
                                "content": [
                                    {"type": "text", "text": json.dumps(result, sort_keys=True)}
                                ],
                                "is_error": "error" in result,
                            }
                        ],
                    )

    def _restore(self, events: Sequence[Mapping[str, Any]]) -> _Preparation:
        state = _Preparation()
        calls = {
            str(event.get("id")): event
            for event in events
            if event.get("type") == "agent.custom_tool_use"
        }
        uses = {
            str(event.get("id")): event for event in events if event.get("type") == "agent.tool_use"
        }
        for event in events:
            if event.get("type") == "user.custom_tool_result" and not event.get("is_error"):
                call = calls.get(str(event.get("custom_tool_use_id")), {})
                if call.get("name") == "mc_prepare":
                    state.offered = True
                elif (
                    call.get("name") == "mc_signal"
                    and isinstance(call.get("input"), Mapping)
                    and call["input"].get("name") == "env.prepared"
                ):
                    state.ready = True
            elif event.get("type") == "agent.tool_result" and not event.get("is_error"):
                use = uses.get(str(event.get("tool_use_id")), {})
                arguments = use.get("input")
                command = arguments.get("command") if isinstance(arguments, Mapping) else None
                if use.get("name") == "bash" and command in self._commands:
                    state.completed.add(str(command))
        return state

    async def _permission(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
        state: _Preparation,
        kind: EffectKind,
    ) -> dict[str, Any] | None:
        if not state.ready:
            command = call.arguments.get("command")
            if (
                state.offered
                and call.name == "bash"
                and command in self._commands
                and await self._gate.admit(operation, identity, call, kind)
            ):
                return {"result": "allow"}
            return {
                "result": "deny",
                "deny_message": "Complete mc_prepare and report env.prepared before other tools",
            }
        return await self._gate.permission(operation, identity, call, kind)

    async def _custom(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
        state: _Preparation,
    ) -> dict[str, Any] | None:
        if not await self._gate.admit(operation, identity, call):
            return {"error": "effect_not_admitted"}
        if call.name == "mc_prepare":
            return {"commands": list(self._commands), "signal_after": "env.prepared"}
        if call.name == "mc_signal":
            is_prepared = call.arguments.get("name") == "env.prepared"
            if is_prepared and (not state.offered or not set(self._commands) <= state.completed):
                return {"error": "mission_layer_not_completed"}
            result = await self._signal(identity, call)
            if "error" in result:
                return result
            if is_prepared:
                # Full replacement while idle, preserving the admitted custom/MCP tools.
                await self._client.update_session(
                    call.session_id, {"agent": {"tools": list(self._steady_tools)}}
                )
            return result
        if not state.ready:
            return {"error": "environment_not_prepared"}
        if call.name == "mc_record_intent":
            return {"intent_ref": call.native_ref}
        if call.name == "mc_request_approval":
            return await self._gate.permission(operation, identity, call)
        try:
            if call.name == "mc_publish":
                return await self._publish(operation, identity, call)
            return await self._governed.execute(
                operation,
                identity,
                call,
                tool_name="repo_pr" if call.name == "mc_open_pr" else None,
            )
        except GovernedRejected as error:
            return {"error": error.code}

    async def _publish(
        self,
        operation: OperationExecutionRequest,
        identity: LaneExecutionIdentity,
        call: HostedCall,
    ) -> dict[str, Any] | None:
        binding = ProviderExecutionBinding.carried_by(operation)
        if (
            binding is None
            or not binding.repo_url
            or not binding.repo_commit
            or not binding.repo_ref
        ):
            return {"error": "publication_requires_a_bound_repository"}
        branch = mission_branch(identity.run_key, identity.activation_key)
        if call.arguments.get("branch") != branch:
            return {"error": "publication_branch_not_admitted"}
        deadline = asyncio.get_running_loop().time() + self._custody_wait
        while True:
            files = [
                item
                for item in await self._client.session_files(call.session_id)
                if str(item.get("filename") or "").split("/")[-1] == "mc.bundle"
            ]
            if files or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(min(0.25, max(0, deadline - asyncio.get_running_loop().time())))
        if not files:
            return {
                "required_action": "write_bundle",
                "command": f"git bundle create /mnt/session/outputs/mc.bundle {branch}",
            }
        if len(files) != 1:
            return {"error": "publication_bundle_ambiguous"}
        file_id = str(files[0]["id"])
        content = await self._client.download_file(file_id)
        if self._artifacts is None:
            return {"error": "publication_custody_unavailable"}
        bundle_ref = await self._artifacts.stage(
            request_scope=identity.request_scope,
            name=f"hosted-publication/{call.native_ref.removeprefix('sha256:')}/candidate.bundle",
            content=content,
            media_type="application/x-git-bundle",
        )
        publication = HostedCall(
            call.session_id,
            call.turn_id,
            call.call_id,
            "mc_publish",
            {
                "session_id": call.session_id,
                "file_id": file_id,
                "bundle_digest": f"sha256:{sha256(content).hexdigest()}",
                "bundle_ref": bundle_ref,
                "repository": binding.repo_url,
                "base_commit": binding.repo_commit,
                "branch": branch,
            },
        )
        pushed = await self._governed.execute(operation, identity, publication)
        if pushed is None or pushed.get("status") != "executed":
            return pushed
        receipt = pushed.get("receipt") or {}
        if receipt.get("outcome") not in {"applied", "noop"}:
            return pushed
        request = HostedCall(
            call.session_id,
            call.turn_id,
            call.call_id,
            "repo_pr",
            {
                "repository": binding.repo_url,
                "branch": branch,
                "base": binding.repo_ref,
                "title": str(
                    call.arguments.get("message") or f"Mission {identity.run_key} results"
                )[:256],
                "body": str(call.arguments.get("message") or ""),
                "draft": True,
            },
        )
        return await self._governed.execute(operation, identity, request)

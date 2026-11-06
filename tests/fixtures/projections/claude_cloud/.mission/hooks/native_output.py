"""Claude Code's native hook answers: ``.mission/hooks/native_output.py`` on the Claude lanes.

``claude_agent_sdk`` and ``claude_cloud`` (OC-R3). The lane's Host Projection writer
(``host_files.py``) places this file verbatim beside the hook runner (``.mission/hooks/run.py``)
and the Telemetry Hook Pack script, which load it from that
directory: the scripts are lane-neutral and the answer shape is the lane's. Standard library
only, Python 3.8 or newer: the workspace's Python runs it without Mission Control installed.
"""

from __future__ import annotations

import json
from typing import Any

CLAUDE_EVENT = {
    "session_start": "SessionStart",
    "session_end": "SessionEnd",
    "before_prompt": "UserPromptSubmit",
    "before_tool": "PreToolUse",
    "before_shell": "PreToolUse",
    "before_mcp": "PreToolUse",
    "after_tool": "PostToolUse",
    "after_shell": "PostToolUse",
    "after_file_edit": "PostToolUse",
    "after_tool_failure": "PostToolUseFailure",
    "before_compaction": "PreCompact",
    "after_compaction": "PostCompact",
    "subagent_start": "SubagentStart",
    "subagent_stop": "SubagentStop",
    "stop": "Stop",
}


def native_output(event: str, lane_profile: str, result: dict[str, Any]) -> tuple[str, int]:
    """Translate a merged ``mc.hook_result.v1`` into Claude Code's hook stdout and exit code."""
    decision = result.get("decision", "allow")
    reason = result.get("reason")
    context = result.get("additional_context")
    message = result.get("message")
    native = CLAUDE_EVENT.get(event, "")
    specific: dict[str, Any] = {"hookEventName": native}
    out: dict[str, Any] = {}
    if native == "PreToolUse":
        specific["permissionDecision"] = decision
        if reason:
            specific["permissionDecisionReason"] = reason
        if result.get("updated_input") is not None:
            specific["updatedInput"] = result["updated_input"]
    elif decision in {"deny", "defer"}:
        out["decision"] = "block"
        out["reason"] = reason or "blocked by Mission Control hook"
    if context:
        specific["additionalContext"] = context
    if message:
        out["systemMessage"] = message
    if len(specific) > 1:
        out["hookSpecificOutput"] = specific
    refused = decision == "deny"
    return json.dumps(out), 2 if refused and native != "PreToolUse" else 0


def native_gate_output(lane: str, decision: str, reason: str) -> dict[str, Any]:
    """A synchronous Signal Ingress gate answer: the cloud session's PreToolUse/stop shape on
    ``claude_cloud``, a settings-file ``block`` otherwise."""
    refused = decision != "allow"
    if lane == "claude_cloud":
        if decision == "stop":
            return {"continue": False, "stopReason": reason}
        return (
            {}
            if not refused
            else {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    return {"decision": "block", "reason": reason}

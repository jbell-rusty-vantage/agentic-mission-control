"""Cursor's native hook answers: ``.mission/hooks/native_output.py`` on the Cursor lanes (OC-R3).

The lane's Host Projection writer (``host_files.py``) places this file verbatim beside the hook
runner (``.mission/hooks/run.py``) and the Telemetry Hook Pack script,
which load it from that directory: the scripts are lane-neutral and the answer shape is the
lane's. Standard library only, Python 3.8 or newer: the workspace's Python runs it without
Mission Control installed.
"""

from __future__ import annotations

import json
from typing import Any

PERMISSION_EVENTS = {
    "before_tool",
    "before_shell",
    "before_mcp",
    "subagent_start",
    "before_prompt",
}


def native_output(event: str, lane_profile: str, result: dict[str, Any]) -> tuple[str, int]:
    """Translate a merged ``mc.hook_result.v1`` into Cursor's hook stdout and exit code."""
    decision = result.get("decision", "allow")
    reason = result.get("reason")
    context = result.get("additional_context")
    message = result.get("message")
    # Headless Cursor does not enforce "ask", so defer becomes deny.
    out: dict[str, Any] = {}
    refused = decision in {"deny", "defer"}
    if event == "before_prompt":
        out["continue"] = not refused
    elif event in PERMISSION_EVENTS:
        out["permission"] = "deny" if refused else "allow"
    if refused and reason:
        out["agent_message"] = reason
    if message:
        out["user_message"] = message
    if result.get("updated_input") is not None:
        out["updated_input"] = result["updated_input"]
    if context:
        out["additional_context"] = context
    return json.dumps(out), 2 if refused and event in PERMISSION_EVENTS else 0


def native_gate_output(lane: str, decision: str, reason: str) -> dict[str, Any]:
    """A synchronous Signal Ingress gate answer in Cursor's permission shape."""
    refused = decision != "allow"
    output: dict[str, Any] = {"permission": "deny" if refused else "allow"}
    if refused:
        output["agent_message"] = reason
    return output

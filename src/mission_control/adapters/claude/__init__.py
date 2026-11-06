"""The local Claude Agent SDK lane (`claude_agent_sdk`; MP-07 / OVE-70).

`harness.ClaudeAgentSdkHarness` is the Session Lane; `transport.SdkClientFactory` is its
production client factory over the pinned `claude-agent-sdk==0.2.165`; `describe` owns the
declared describe matrices of the Claude profiles (OC-R3); `frames`, `session`, `hooks`,
`permissions` and `workspace` are the mapping, stream ownership, Kernel Hook, approval-binding
and state-root pieces. Imported by name (not re-exported here, to keep this package import
light): `approvals.BrokerPermissionBinding` (MP-11 broker port), `continuation` (MP-12
snapshots, hydrator and registration), `host` (worker-host gate) and `compose` (composition
helpers). The exports below load lazily (PEP 562) so that the application's describe aggregator
can read `describe` without importing the harness.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mission_control.adapters.claude.describe import PROFILE
    from mission_control.adapters.claude.harness import (
        AuthAdmitter,
        ClaudeAgentSdkHarness,
        ClaudeLaneError,
        ClaudeLaneSettings,
        StaticAuthAdmitter,
    )
    from mission_control.adapters.claude.permissions import (
        DenyWithoutGateway,
        PermissionBindingPort,
        PermissionOutcome,
        PermissionRequest,
    )
    from mission_control.adapters.claude.session import (
        ClaudeClient,
        ClaudeClientFactory,
        LiveSession,
    )
    from mission_control.adapters.claude.workspace import AllocatedWorkspace, ClaudeWorkspace

_EXPORTS = {
    "PROFILE": "describe",
    "AllocatedWorkspace": "workspace",
    "AuthAdmitter": "harness",
    "ClaudeAgentSdkHarness": "harness",
    "ClaudeClient": "session",
    "ClaudeClientFactory": "session",
    "ClaudeLaneError": "harness",
    "ClaudeLaneSettings": "harness",
    "ClaudeWorkspace": "workspace",
    "DenyWithoutGateway": "permissions",
    "LiveSession": "session",
    "PermissionBindingPort": "permissions",
    "PermissionOutcome": "permissions",
    "PermissionRequest": "permissions",
    "StaticAuthAdmitter": "harness",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{module}"), name)


__all__ = [
    "PROFILE",
    "AllocatedWorkspace",
    "AuthAdmitter",
    "ClaudeAgentSdkHarness",
    "ClaudeClient",
    "ClaudeClientFactory",
    "ClaudeLaneError",
    "ClaudeLaneSettings",
    "ClaudeWorkspace",
    "DenyWithoutGateway",
    "LiveSession",
    "PermissionBindingPort",
    "PermissionOutcome",
    "PermissionRequest",
    "StaticAuthAdmitter",
]

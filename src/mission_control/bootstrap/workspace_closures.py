"""The Application Profile's `[workspace]` Workspace Closure policy at composition (OVE-204).

The worker composition reads it once and hands it to the Deep Agents adapter; it is not part of
`ResolvedRuntime` (a cap change must not change `runtime_digest`). No application id (fixtures,
tests) is the model defaults; a profile that does not load disables closures (logged), never a
guessed cap.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mission_control.bootstrap.application_profiles import load_application_profile
from mission_control.domain.resolution.profiles import WorkspaceClosureProfile

_LOG = logging.getLogger(__name__)
DISABLED = WorkspaceClosureProfile(closure_enabled=False)


def workspace_closure_profile(root: Path, application_id: str | None) -> WorkspaceClosureProfile:
    if application_id is None:
        return WorkspaceClosureProfile()
    try:
        return load_application_profile(root, application_id).profile.workspace
    except (OSError, ValueError):
        _LOG.warning(
            "the %s Application Profile did not load; workspace closures are disabled",
            application_id,
            exc_info=True,
        )
        return DISABLED


__all__ = ["workspace_closure_profile"]

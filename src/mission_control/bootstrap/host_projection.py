"""Composition of the Host Projection port (OC-R3): the only place its lane writers are named.

Each lane package exports its `LaneHostFiles` by profile (`adapters/<lane>/host_files.py`;
the two hosted agent APIs share the remote-session base's writer). The writers are pure and
stateless, so one composed `HostProjectors` serves every process: the launch author's
materialization digests, the lanes' `prepare` re-render, the catalog render preview and the
hosted projection.
"""

from __future__ import annotations

from typing import Final

from mission_control.adapters.claude.host_files import HOST_FILES as CLAUDE_HOST_FILES
from mission_control.adapters.codex.host_files import HOST_FILES as CODEX_HOST_FILES
from mission_control.adapters.cursor.host_files import HOST_FILES as CURSOR_HOST_FILES
from mission_control.adapters.deep_agents.host_files import HOST_FILES as DEEP_AGENTS_HOST_FILES
from mission_control.adapters.remote_session.host_files import HOST_FILES as HOSTED_HOST_FILES
from mission_control.application.agentic_components.projections import HostProjectors


def compose_host_projectors() -> HostProjectors:
    writers = {
        **DEEP_AGENTS_HOST_FILES,
        **CURSOR_HOST_FILES,
        **CLAUDE_HOST_FILES,
        **CODEX_HOST_FILES,
        **HOSTED_HOST_FILES,
    }
    total = sum(
        len(group)
        for group in (
            DEEP_AGENTS_HOST_FILES,
            CURSOR_HOST_FILES,
            CLAUDE_HOST_FILES,
            CODEX_HOST_FILES,
            HOSTED_HOST_FILES,
        )
    )
    if len(writers) != total:
        raise ValueError("two lane packages export a Host Projection writer for one profile")
    return HostProjectors(writers)


HOST_PROJECTORS: Final = compose_host_projectors()

__all__ = ["HOST_PROJECTORS", "compose_host_projectors"]

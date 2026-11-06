"""The Cursor Discovery Proofs (SPEC-02 section 6; MO-34).

`cursor_local` (`setting_readback`): the Cursor SDK reports no per-item load list, so the proof
is the SDK's read-back of the agent (`get_agent`): a local agent whose project root is the
leased workspace loads that workspace's `.cursor` files through its `project` setting source
(the lane creates every agent with `setting_sources=["project"]`). Only then does the report
list the skill directories there and digest the instruction overlay and hook config as the
agent's project source reads them; an agent rooted anywhere else reports nothing and proves
nothing. A fired hook still raises the ladder to `exercised` on its own.

`cursor_cloud` (`materialization_signal`): the Telemetry Hook Pack's first signal from inside
the VM (`application/environments/discovery.materialization_signal_report`); what it must read
is the expectation the cloud prepare records over the files committed on the mission branch
(`committed_expectation`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from mission_control.adapters.cursor.bridge import AgentReadback
from mission_control.application.agentic_components.layering import LayeringReceipt
from mission_control.application.environments.discovery import (
    discovery_expectation,
    observed_files,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import LAYERING_LAYOUTS
from mission_control.domain.context.render import bytes_digest
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
)

LOCAL = LaneProfile.CURSOR_LOCAL
SKILL_FILE = "SKILL.md"


def _same_directory(reported: str, workspace: Path) -> bool:
    if not reported:
        return False
    return os.path.normcase(os.path.realpath(reported)) == os.path.normcase(
        os.path.realpath(workspace)
    )


def _read_digest(path: Path) -> str | None:
    try:
        return bytes_digest(path.read_bytes())
    except OSError:
        return None


def setting_readback_report(readback: AgentReadback, workspace: Path) -> DiscoveryReport:
    """The `cursor_local` report of one agent read-back over the leased `workspace` (blocking
    file reads; call it off the event loop)."""

    source = f"sdk:get_agent:{readback.agent_id}"
    if readback.runtime != "local" or not _same_directory(readback.cwd, workspace):
        return DiscoveryReport(lane_profile=LOCAL, mechanism="setting_readback", source=source)
    skills_root = workspace / LAYERING_LAYOUTS[LOCAL].skills
    skills = (
        sorted(entry.name for entry in skills_root.iterdir() if (entry / SKILL_FILE).is_file())
        if skills_root.is_dir()
        else []
    )
    return DiscoveryReport(
        lane_profile=LOCAL,
        mechanism="setting_readback",
        items=tuple(DiscoveryItem(kind="skill", name=name) for name in skills),
        digests={path: _read_digest(workspace / path) for path in observed_files(LOCAL)},
        source=source,
    )


def committed_expectation(
    layering: LayeringReceipt, files: Mapping[str, bytes]
) -> DiscoveryExpectation | None:
    """The `cursor_cloud` expectation over the layered files committed on the mission branch."""

    return discovery_expectation(
        LaneProfile.CURSOR_CLOUD,
        layering,
        {path: bytes_digest(content) for path, content in files.items()},
    )


__all__ = ["committed_expectation", "setting_readback_report"]

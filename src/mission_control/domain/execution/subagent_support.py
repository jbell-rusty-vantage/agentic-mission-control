"""Derived per-lane subagent field rows for lanes without an adapter (P1 subagents, WP-S5).

The one vocabulary is ``domain/capabilities/subagents.py::SUBAGENT_FIELDS``; the verdicts are
``SubagentFieldVerdict``. The Deep Agents lane declares its own row beside its describe
matrix (``application/execution/harness/describe.py``, re-exported by
``adapters/deep_agents/lane.py``); the file lanes (Cursor, Claude, Codex, local and cloud) are
**derived** here from the projection layout table
(``domain/capabilities/layouts.py::LANE_LAYOUTS``) until each gets an adapter that signs a
receipt; the hosted agent APIs run no provider-native subagents, so every field is
``unsupported``. The lane describe (``application/execution/harness/describe.py``) carries
each row as ``subagents.fields`` on the persisted describe document (release 1.4.3,
migration 0046), which is what compile enforces and the coordinator authors against.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import LANE_LAYOUTS
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS
from mission_control.domain.execution.lanes import SubagentFieldVerdict

SubagentFieldSupport = Mapping[str, SubagentFieldVerdict]

# Profile fields the file-lane projections report as a loss and still run without
# (`projections._SUBAGENT_FIELD_LOSS`); every other field a layout lacks is unsupported.
_PROJECTION_DEGRADES: Final[Mapping[str, str]] = {
    "model": "model",
    "tools": "tools",
    "skills": "skills",
    "mcp_servers": "mcp_servers",
    "readonly": "readonly",
    "background": "background",
    "max_turns": "max_turns",
    "interrupt_on": "interrupt_on",
    "context_mode.fork": "context_mode",
}


def derived_file_lane_row(lane: LaneProfile) -> dict[str, SubagentFieldVerdict]:
    """A file lane's row from its projection layout: native keys, documented losses, refusals."""

    layout = LANE_LAYOUTS[lane].subagents
    native_keys = set(layout.fields) if layout is not None else set()
    row: dict[str, SubagentFieldVerdict] = dict.fromkeys(SUBAGENT_FIELDS, "unsupported")
    if layout is not None:
        row["kind.sync"] = "native"
        row["placement.in_process"] = "native"
        # A seeded profile without seeds is the plain agent file every file lane writes.
        row["capabilities.seeded"] = "native"
        for field, layout_key in _PROJECTION_DEGRADES.items():
            row[field] = "native" if layout_key in native_keys else "degraded"
    return row


def unsupported_row() -> dict[str, SubagentFieldVerdict]:
    """The row of a lane that runs no provider-native subagents."""

    return dict.fromkeys(SUBAGENT_FIELDS, "unsupported")


def complete_row(
    lane: str, row: Mapping[str, SubagentFieldVerdict]
) -> dict[str, SubagentFieldVerdict]:
    """The row in vocabulary order; a missing or unknown field is a programming error."""

    missing = sorted(set(SUBAGENT_FIELDS) - set(row))
    unknown = sorted(set(row) - set(SUBAGENT_FIELDS))
    if missing or unknown:
        raise ValueError(
            f"lane {lane} subagent support must name every field once; "
            f"missing={missing} unknown={unknown}"
        )
    return {field: row[field] for field in SUBAGENT_FIELDS}


__all__ = ["SubagentFieldSupport", "complete_row", "derived_file_lane_row", "unsupported_row"]

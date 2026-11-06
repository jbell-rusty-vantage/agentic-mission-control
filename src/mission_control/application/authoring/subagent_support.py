"""Per-lane subagent field support: what every lane does with each ``SUBAGENT_FIELDS`` name.

Since release 1.4.3 the table lives **on the lane describe** (``subagents.fields`` of
``mc.lane_describe.v2``, ``application/execution/harness/describe.py``, persisted by
migration 0046), so compile, ``GET .../lanes/{profile}`` and the ledger read one document.
This module is the compile-time reader of that table.

Where each row comes from (PROCESS §2.2 rule 3: the lane adapter owns its row):

- ``deep_agents``: declared beside its describe matrix
  (``describe.DEEP_AGENTS_SUBAGENT_FIELDS``, re-exported by ``adapters/deep_agents/lane.py``)
  and carried by ``DEEP_AGENTS_DESCRIBE``.
- the file lanes (Cursor, Claude, Codex, local and cloud): derived from the projection layout
  table (``domain/execution/subagent_support.py::derived_file_lane_row``) until WP-S5 gives
  each of them an adapter that signs a receipt.
- the hosted agent APIs (``claude_managed``, ``codex_agents``): every field ``unsupported``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from mission_control.application.execution.harness.describe import DECLARED_LANE_MATRICES
from mission_control.domain.capabilities.subagents import SUBAGENT_FIELDS
from mission_control.domain.execution.lanes import SubagentFieldVerdict
from mission_control.domain.execution.subagent_support import SubagentFieldSupport, complete_row


def _declared_rows() -> dict[str, SubagentFieldSupport]:
    rows: dict[str, SubagentFieldSupport] = {}
    for profile, describe in DECLARED_LANE_MATRICES.items():
        if not describe.subagents.fields:
            raise ValueError(f"lane {profile} declares no subagent field support on its describe")
        rows[profile] = complete_row(profile, describe.subagents.fields)
    return rows


SUBAGENT_FIELD_SUPPORT: Final[Mapping[str, SubagentFieldSupport]] = _declared_rows()


def subagent_field_support(lane_profile: str) -> SubagentFieldSupport:
    """One lane's verdict per field, in vocabulary order; an undeclared lane is an error."""

    try:
        return SUBAGENT_FIELD_SUPPORT[lane_profile]
    except KeyError as error:
        raise ValueError(f"lane {lane_profile} has no subagent field support row") from error


__all__ = [
    "SUBAGENT_FIELDS",
    "SUBAGENT_FIELD_SUPPORT",
    "SubagentFieldSupport",
    "SubagentFieldVerdict",
    "subagent_field_support",
]

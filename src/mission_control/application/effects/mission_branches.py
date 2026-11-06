"""Mission branches: the only refs a mission may push (SPEC-01 section 6; SPEC-03 section 1).

Every writable unit of a run writes `mc/{run}/{unit}`. A local lease works on its slot branch
(`mc/ws/<digest>`) and publishes to the mission branch; the Mission Control-owned pre-push
guard admits only `refs/heads/mc/{run}/` for the lease's run, and `repo_pr` opens pull requests
only from such a branch.
"""

from __future__ import annotations

import re
from typing import Final

from mission_control.domain.graph_runtime.identities import UNIT_KEY_PATTERN

MISSION_BRANCH_PREFIX: Final = "mc"
# One path segment of a mission branch: safe as a git ref component and inside a quoted
# POSIX shell word (the pre-push guard embeds the run segment).
_SEGMENT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _segment(value: str, what: str) -> str:
    if not _SEGMENT.fullmatch(value) or ".." in value or value.endswith(".lock"):
        raise ValueError(f"{what} {value!r} is not a mission branch segment")
    return value


def mission_branch_prefix(run_id: str) -> str:
    """`mc/{run}/`: every branch of the run lives under it."""

    return f"{MISSION_BRANCH_PREFIX}/{_segment(run_id, 'run id')}/"


def mission_branch(run_id: str, unit: str) -> str:
    """`mc/{run}/{unit}`: the branch one writable unit of the run publishes."""

    # Canonical runtime unit keys contain a colon, which git refs forbid. Encode only
    # that exact domain shape; arbitrary untrusted segments still fail validation.
    if re.fullmatch(UNIT_KEY_PATTERN, unit):
        unit = unit.replace(":", "-")
    return mission_branch_prefix(run_id) + _segment(unit, "unit")


def is_mission_branch(branch: str, run_id: str) -> bool:
    """Whether `branch` is a branch of `run_id` (`mc/{run}/<segment>[/...]`)."""

    try:
        prefix = mission_branch_prefix(run_id)
    except ValueError:
        return False
    if not branch.startswith(prefix):
        return False
    rest = branch.removeprefix(prefix).split("/")
    return all(_SEGMENT.fullmatch(part) and ".." not in part for part in rest)


__all__ = [
    "MISSION_BRANCH_PREFIX",
    "is_mission_branch",
    "mission_branch",
    "mission_branch_prefix",
]

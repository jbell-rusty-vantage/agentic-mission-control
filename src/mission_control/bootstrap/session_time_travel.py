"""K3 (cross-provider control, 2026-11-05): every Session Lane's `TimeTravelLane` in one list.

The worker (`adapters/temporal/deployment_composition.py::_worker_time_travel`), the operator
API (`bootstrap/api.py::compose_time_travel`) and the technical API
(`bootstrap/runtime_control.py`) register the same lanes beside `deep_agents`:

- `cursor_local`, `cursor_cloud` (`adapters/cursor/time_travel.py`): R1 over the frame
  reader, R2 with the snapshot store (local) or the branch reader (cloud);
- `claude_agent_sdk`, `codex` (`adapters/temporal/provider_lane_composition.py::
  provider_time_travel_lanes`): R1 over the frames, R3 where this process composed the
  harness;
- `claude_managed`, `codex_agents` (`adapters/temporal/hosted_lane_composition.py::
  compose_hosted_time_travel`): R1 over the frames, composed per request scope and wrapped
  by `scoped_lane` so the registry binds the caller's scope.

All of them are `ScopedTimeTravelLane`s (the frame store is tenant scoped); a process that
composes no harness still registers them: an R1 read needs the frames only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mission_control.adapters.cursor.snapshot import SnapshotArtifacts
from mission_control.adapters.cursor.time_travel import (
    BranchTreeReader,
    SnapshotStoreResolver,
    cursor_time_travel_lanes,
)
from mission_control.adapters.temporal.hosted_lane_composition import compose_hosted_time_travel
from mission_control.adapters.temporal.provider_lane_composition import provider_time_travel_lanes
from mission_control.application.execution.harness.time_travel import (
    TimeTravelLane,
    scoped_lane,
)
from mission_control.application.frames.sink import FrameReader

HOSTED_PROFILES = ("claude_managed", "codex_agents")


def session_lane_time_travel(
    frames: FrameReader,
    *,
    snapshots: SnapshotArtifacts | SnapshotStoreResolver | None = None,
    branches: BranchTreeReader | None = None,
    claude: Any = None,
    codex: Any = None,
) -> tuple[TimeTravelLane, ...]:
    """The session lanes' time-travel lanes for `TimeTravelRegistry.register_all`."""

    store = snapshots if snapshots is not None and not callable(snapshots) else None

    def hosted(profile: str) -> Callable[[str], TimeTravelLane]:
        return lambda scope: compose_hosted_time_travel(frames=frames, request_scope=scope)[profile]

    return (
        *cursor_time_travel_lanes(frames=frames, snapshots=snapshots, branches=branches),
        *provider_time_travel_lanes(frames, store, claude=claude, codex=codex),
        *(scoped_lane(profile, hosted(profile)) for profile in HOSTED_PROFILES),
    )


__all__ = ["HOSTED_PROFILES", "session_lane_time_travel"]

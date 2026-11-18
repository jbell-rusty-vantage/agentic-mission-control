"""Builders, constants and fakes that other test files import.

Moved from tests/unit/watchers/test_watcher_planner.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from mission_control.domain.programs.watchers import (
    FiringRecord,
    Observation,
    WatcherDescriptor,
    WatcherPlan,
    WatcherPlanInput,
    WatcherSpec,
    compile_watcher,
    plan_watchers,
)
from tests.unit.watchers.fakes import RUN_ID, T0, at


def watcher(watcher_id: str, body: dict[str, Any]) -> WatcherDescriptor:
    return compile_watcher(
        WatcherSpec.model_validate(body),
        watcher_id=watcher_id,
        origin="manifest",
        pointer=f"/mission/controls/watchers/{watcher_id}",
    )


def signal(
    signal_type: str, data: dict[str, Any], *, when: datetime, ref: str, trust: Any = "run_token"
) -> Observation:
    return Observation(
        source="signal", ref=ref, types=(signal_type,), at=when, data=data, trust=trust
    )


def plan(
    descriptors: Sequence[WatcherDescriptor],
    observations: Sequence[Observation] = (),
    *,
    now: datetime | None = None,
    history: Sequence[FiringRecord] = (),
    **kwargs: Any,
) -> WatcherPlan:
    return plan_watchers(
        WatcherPlanInput(
            run_id=RUN_ID,
            descriptors=tuple(descriptors),
            observations=tuple(observations),
            history=tuple(history),
            armed_at=T0,
            now=now or at(3600),
            run=kwargs.pop("run", {"phase": "active", "branch_prefix": "mc/run-1/"}),
            **kwargs,
        )
    )

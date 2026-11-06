"""Placement reservations last through provider custody; waits are delegated to Temporal."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from mission_control.application.execution.harness.dispatch import ProviderCapacityLimited
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.placement import PlacementLimit
from mission_control.domain.execution.usage_admission import ProviderLimitSignal


class PlacementStore(Protocol):
    async def reserve(
        self, scope: str, execution: UUID, profile: str, limit: PlacementLimit, now: datetime
    ) -> bool: ...
    async def release(self, scope: str, execution: UUID) -> None: ...


class PlacementAdmission:
    def __init__(
        self, store: PlacementStore, limits: Mapping[LaneProfileName, PlacementLimit]
    ) -> None:
        self._store, self._limits = store, dict(limits)

    async def reserve(self, scope: str, execution: UUID, profile: str, now: datetime) -> None:
        limit = self._limits.get(cast(LaneProfileName, profile))
        if limit is None:
            return
        if not await self._store.reserve(scope, execution, profile, limit, now):
            raise ProviderCapacityLimited(
                ProviderLimitSignal(
                    lane_profile=cast(LaneProfileName, profile),
                    kind="overloaded",
                    source="mission_control.placement_limits",
                    resets_at=now + timedelta(seconds=limit.retry_after_s),
                    native_code="PLACEMENT_LIMIT",
                )
            )

    async def release(self, scope: str, execution: UUID) -> None:
        await self._store.release(scope, execution)


class InMemoryPlacementStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._records: dict[tuple[str, UUID], tuple[str, datetime, bool]] = {}

    async def reserve(
        self, scope: str, execution: UUID, profile: str, limit: PlacementLimit, now: datetime
    ) -> bool:
        async with self._lock:
            prior = self._records.get((scope, execution))
            if prior is not None and prior[2]:
                return True
            records = [
                record
                for (record_scope, _), record in self._records.items()
                if record_scope == scope and record[0] == profile
            ]
            active = sum(record[2] for record in records)
            launches = sum(record[1] > now - timedelta(minutes=1) for record in records)
            if active >= limit.max_active or (
                limit.launches_per_minute is not None and launches >= limit.launches_per_minute
            ):
                return False
            self._records[scope, execution] = (profile, now.astimezone(UTC), True)
            return True

    async def release(self, scope: str, execution: UUID) -> None:
        async with self._lock:
            prior = self._records.get((scope, execution))
            if prior is not None:
                self._records[scope, execution] = (*prior[:2], False)

"""Builders, constants and fakes that other test files import.

Moved from tests/unit/recovery/test_seeded_fork_saga.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.recovery.runtime_recovery import (
    ForkMaterializationObservation,
    InMemoryForkRepository,
    RuntimeForkService,
)
from tests.support.unit.runtime.runtime_recovery_stage3 import ForkAuthority, ForkMaterializer


class ReconcilingMaterializer(ForkMaterializer):
    """A materializer whose recorded lineage a replay reconciles."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded: Any = None

    async def materialize(self, request, admission):  # type: ignore[no-untyped-def]
        self.recorded = await super().materialize(request, admission)
        return self.recorded

    async def reconcile_materialization(self, _request, _admission):  # type: ignore[no-untyped-def]
        return ForkMaterializationObservation(status="materialized", materialization=self.recorded)


def saga() -> tuple[RuntimeForkService, InMemoryForkRepository]:
    repository = InMemoryForkRepository()
    return (
        RuntimeForkService(
            repository=repository,
            authority=ForkAuthority(),  # type: ignore[arg-type]
            materializer=ReconcilingMaterializer(),  # type: ignore[arg-type]
        ),
        repository,
    )

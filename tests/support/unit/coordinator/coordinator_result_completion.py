"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_coordinator_result_completion.py.
"""

from __future__ import annotations

from mission_control.application.coordinator.coordinator_results import (
    InMemoryWorkflowResultRepository,
)


class AmbiguousFirstSave:
    def __init__(self) -> None:
        self.inner = InMemoryWorkflowResultRepository()
        self.first = True

    async def save(self, result):
        persisted = await self.inner.save(result)
        if self.first:
            self.first = False
            raise TimeoutError("database response was ambiguous")
        return persisted

    async def get(self, tenant_scope: str, request_scope: str, run_id: str):
        return await self.inner.get(tenant_scope, request_scope, run_id)

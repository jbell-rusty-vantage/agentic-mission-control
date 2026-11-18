"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_fork_templates.py.
"""

from __future__ import annotations

from datetime import datetime

from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.forks import ForkPatchChange, RunForkPatch


class MemoryTemplates:
    def __init__(self) -> None:
        self.stored: dict[tuple[str, str], dict[str, OperationExecutionRequest]] = {}

    async def list_templates(
        self, *, request_scope: str, semantic_input_binding_ref: str
    ) -> dict[str, OperationExecutionRequest]:
        return dict(self.stored.get((request_scope, semantic_input_binding_ref), {}))

    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        templates: dict[str, OperationExecutionRequest],
        recorded_at: datetime,
    ) -> None:
        del recorded_at
        self.stored[(request_scope, semantic_input_binding_ref)] = dict(templates)


def _patch(*changes: tuple[str, str]) -> RunForkPatch:
    snapshot = "run-snapshot:" + "a" * 64
    return RunForkPatch.create(
        source_snapshot_id=snapshot,
        source_snapshot_digest="sha256:" + "b" * 64,
        target_admission_request_ref="run-request:tenant-1:operator:fork",
        changes=tuple(ForkPatchChange(path=path, value=value) for path, value in changes),
        invalidation_frontier=("review",),
    )

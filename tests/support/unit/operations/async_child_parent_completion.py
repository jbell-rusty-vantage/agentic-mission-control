"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_async_child_parent_completion.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class Lineage:
    def __init__(self, *child_ids: str, parent_binding_id: str = "binding-1") -> None:
        self.child_ids = list(child_ids)
        self.parent_binding_id = parent_binding_id

    async def list_children(self, request_scope: str, parent_run_id: str) -> tuple[Any, ...]:
        del request_scope, parent_run_id
        return (
            SimpleNamespace(child_execution_id="foreign", parent_binding_id="another-binding"),
            *(
                SimpleNamespace(child_execution_id=item, parent_binding_id=self.parent_binding_id)
                for item in self.child_ids
            ),
        )

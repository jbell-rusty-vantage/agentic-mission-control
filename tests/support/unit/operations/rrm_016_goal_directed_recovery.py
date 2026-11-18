"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_goal_loop_crash_recovery.py.
"""

from __future__ import annotations

from typing import Any


class _Templates:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    async def get_template(self, *, operation_role: str, **_: object) -> Any:
        return self._values[operation_role]

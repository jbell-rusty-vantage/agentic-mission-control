"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_frame_facts.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.policies.contracts import LifecycleCommand


class _RunControl:
    """In-memory run control wrapper granting the projector's permission."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self.commands: list[LifecycleCommand] = []

    async def execute(self, lifecycle: LifecycleCommand) -> Any:
        self.commands.append(lifecycle)
        return await self.service.execute(lifecycle)

    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return await self.service.get_run(request_scope, run_id)

"""Temporal activities of recursive composition (OVE-176): thin calls into the application.

Registered on the family worker beside the Stage Graph and Goal Loop activities; the family
workflows call them through ``workflows/nested_body.py``.
"""

from __future__ import annotations

from temporalio import activity

from mission_control.application.programs.nested_bodies import NestedProgramService
from mission_control.domain.programs.nested import (
    NestedActivation,
    NestedActivationRequest,
    NestedControlReceipt,
    NestedControlRequest,
    NestedSettlement,
    NestedSettlementRequest,
)

NESTED_ACTIVATE = "nested_program.activate"
NESTED_SETTLE = "nested_program.settle"
NESTED_PROPAGATE = "nested_program.propagate"


class NestedProgramActivities:
    def __init__(self, service: NestedProgramService) -> None:
        self._service = service

    @activity.defn(name=NESTED_ACTIVATE)
    async def activate(self, request: NestedActivationRequest) -> NestedActivation:
        return await self._service.activate(request)

    @activity.defn(name=NESTED_SETTLE)
    async def settle(self, request: NestedSettlementRequest) -> NestedSettlement:
        return await self._service.settle(request)

    @activity.defn(name=NESTED_PROPAGATE)
    async def propagate(self, request: NestedControlRequest) -> NestedControlReceipt:
        return await self._service.propagate(request)

    def activities(self) -> list[object]:
        return [self.activate, self.settle, self.propagate]

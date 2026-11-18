"""Builders, constants and fakes that other test files import.

Moved from tests/unit/harness/test_hook_callback.py.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mission_control.adapters.cursor.hooks_callback import CursorHookMapper
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    HookTokenContext,
    InMemoryHookIntentLedger,
    InMemoryHookTokenStore,
    KernelHookCall,
)
from mission_control.application.execution.stop_fence import (
    InMemoryStopFenceRepository,
    KernelHookFenceGate,
)
from mission_control.application.frames.sink import InMemoryFrameStore
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.frames.contracts import HarnessExecutionStart, LaneProfile
from tests.support.clock import Clock
from tests.support.ids import INSTALLATION, SCOPE, TENANT
from tests.support.lanes import ACTIVATION_UUID, RUN_UUID

HEID = UUID("55555555-5555-4555-8555-555555555555")
RUN = "run-operation"
SCOPE_BLOCK = {
    "installation_id": str(INSTALLATION),
    "application_id": "biotech",
    "tenant_id": str(TENANT),
}


def _context(generation: int = 1, **changes: Any) -> HookTokenContext:
    return HookTokenContext.model_validate(
        {
            "request_scope": SCOPE,
            "run_id": RUN,
            "attempt_no": generation,
            "generation": generation,
            "harness_execution_id": HEID,
            "lane_profile": "cursor_local",
            "execution_start": HarnessExecutionStart(
                harness_execution_id=HEID,
                request_scope=SCOPE,
                run_key=RUN,
                activation_key="sandbox-agent",
                attempt_no=generation,
                generation=generation,
                lane_profile=LaneProfile.CURSOR_LOCAL,
                native_session_ref="agent-1",
                runtime_kind="cursor",
                provider_kind="cursor_local",
                placement_kind="worker_hosted",
                intended_binding_digest="sha256:" + "c" * 64,
            ),
            "workspace_root": "/lease",
            **changes,
        }
    )


class Stack:
    def __init__(self) -> None:
        self.clock = Clock()
        self.tokens = InMemoryHookTokenStore()
        self.intents = InMemoryHookIntentLedger()
        self.fences = InMemoryStopFenceRepository()
        self.frames = InMemoryFrameStore()
        self.frames.register_run(SCOPE, RUN, RUN_UUID, {"sandbox-agent": ACTIVATION_UUID})
        self.service = HookCallbackService(
            tokens=self.tokens,
            intents=self.intents,
            mapper=CursorHookMapper(),
            fences=KernelHookFenceGate(self.fences),
            frames=self.frames,
            context_reader=lambda _context: "| binding | source |\n| --- | --- |",
            clock=self.clock,
        )

    def call(
        self, hook: str, event: str, payload: dict[str, Any], generation: int = 1
    ) -> KernelHookCall:
        return KernelHookCall(
            kernel_hook_id=hook,
            event=HookEvent(event),
            scope=SCOPE_BLOCK,  # type: ignore[arg-type]
            harness_execution_id=str(HEID),
            generation=generation,
            payload=payload,
        )

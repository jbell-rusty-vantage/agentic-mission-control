"""Fixture-only pause after saved consumer cognition and real worker replacement."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from mission_control.adapters.postgres.run_control import canonical as mc


@dataclass
class SavedConsumerRestart:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    paused: bool = False
    restarted: bool = False
    operation: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def install(self, toolset: Any) -> None:
        settle = toolset.settle_saved

        async def paused_settlement(live: Any, *, fenced: bool = False) -> Any:
            if ":stage:consume:" in live.operation_id and not fenced and not self.paused:
                self.paused = True
                self.operation = live.operation_id
                self.entered.set()
                # Worker shutdown cancels this activity. The replacement worker reuses
                # the persisted result and calls the normal settler on its retry.
                await asyncio.Event().wait()
            return await settle(live, fenced=fenced)

        toolset.settle_saved = paused_settlement

    async def snapshot(self, stack: Any, scope: str, run_id: str, script: Any) -> dict[str, Any]:
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            saved = await connection.fetch(
                "SELECT settlement_id::text, binding_id, saved_result_digest, settlement "
                "FROM mission_control.invocation_settlement WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND run_id=$4::uuid AND operation_ref=$5",
                *args,
                run_id,
                self.operation,
            )
            outputs = await connection.fetch(
                "SELECT output_revision_id::text, content_digest "
                "FROM mission_control.output_revision "
                "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND run_id=$4::uuid ORDER BY output_revision_id",
                *args,
                run_id,
            )
            effects = await connection.fetch(
                "SELECT effect_key, bound_effect_digest, terminal_receipt_ref, "
                "receipt_digest, state "
                "FROM mission_control.knowledge_operation_journal WHERE "
                "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                "AND originating_origin#>>'{mission,runId}'=$4 ORDER BY effect_key",
                *args,
                run_id,
            )
        return {
            "model_calls": [row for row in stack.model_log if row["run_id"] == run_id],
            "tool_calls": [row for row in script.calls if row["run_id"] == run_id],
            "saved": [dict(row) for row in saved],
            "outputs": [dict(row) for row in outputs],
            "effects": [dict(row) for row in effects],
        }

    async def progress(self, stack: Any, scope: str, run_id: str, script: Any) -> None:
        if not self.entered.is_set() or self.restarted:
            return
        from tests.fixtures.rrm009_cancellation import restart_workers

        self.before = await self.snapshot(stack, scope, run_id, script)
        assert len(self.before["saved"]) == 1, "consumer cognition must already be durable"
        assert self.before["saved"][0]["settlement"] != "settled"
        self.restarted = True
        await restart_workers(stack)

    async def verify(self, stack: Any, scope: str, run_id: str, script: Any) -> None:
        assert self.restarted and self.before is not None
        self.after = await self.snapshot(stack, scope, run_id, script)
        assert self.after["model_calls"] == self.before["model_calls"]
        assert self.after["tool_calls"] == self.before["tool_calls"]
        assert self.after["outputs"] == self.before["outputs"]
        assert self.after["effects"] == self.before["effects"]
        assert len(self.after["saved"]) == 1
        assert (
            self.after["saved"][0]["saved_result_digest"]
            == self.before["saved"][0]["saved_result_digest"]
        )
        assert self.after["saved"][0]["settlement"] == "settled"

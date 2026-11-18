"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_nested_body_runtime.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mission_control.domain.authoring.nested_bodies import NestedBody, NestedExport
from mission_control.domain.policies.contracts import (
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)
from tests.support.run_control import command, request

NOW = datetime(2026, 10, 29, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
SCOPE = "tenant-1"


def body(*, depth: int = 1, timing: str = "final", required: bool = True) -> NestedBody:
    return NestedBody(
        host_id="research",
        node_key="research",
        position="research",
        behavior="stage_graph",
        family="StageGraph",
        depth=depth,
        max_depth=2,
        definition_digest=DIGEST,
        blueprint_digest=DIGEST,
        exports=(
            NestedExport(output="report", source="inner.report"),
            NestedExport(output="note", source="notes.note", timing=timing, required=required),
        ),
    )


async def parent_with_reservation(control: Any, amount: int = 40) -> str:
    admitted = await control.admit(request())
    run_id = admitted.run_id
    assert run_id
    await control.execute(command(run_id, 1, "start", StartAction()))
    reserved = await control.execute(
        command(
            run_id,
            2,
            "reserve-unit",
            ReserveBudgetAction(reservation_id="unit-1", amounts={"tokens.total": amount}),
        )
    )
    assert reserved.status == CommandStatus.ACCEPTED
    return run_id

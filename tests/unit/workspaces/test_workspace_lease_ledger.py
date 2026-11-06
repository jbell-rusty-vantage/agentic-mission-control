"""MP-04 fenced lease ledger semantics on the in-memory store (the same scenarios run on real
PostgreSQL in tests/integration/postgres/test_workspace_lease_races.py)."""

from __future__ import annotations

from mission_control.application.execution.harness.leases import InMemoryWorkspaceLeaseStore
from tests.unit.workspaces.lease_scenarios import (
    concurrent_acquisition_has_one_winner,
    expired_cursor_holder_requires_recovery_before_replacement,
    stale_generation_writes_are_rejected,
    stale_write_racing_a_takeover_never_both_apply,
)

SCOPE = "scope/in-memory"


async def test_concurrent_acquisition_has_one_winner() -> None:
    await concurrent_acquisition_has_one_winner(InMemoryWorkspaceLeaseStore(), SCOPE)


async def test_stale_generation_writes_are_rejected() -> None:
    await stale_generation_writes_are_rejected(InMemoryWorkspaceLeaseStore(), SCOPE)


async def test_a_stale_write_racing_a_takeover_never_both_apply() -> None:
    await stale_write_racing_a_takeover_never_both_apply(InMemoryWorkspaceLeaseStore(), SCOPE)


async def test_expired_cursor_holder_requires_recovery_before_replacement() -> None:
    await expired_cursor_holder_requires_recovery_before_replacement(
        InMemoryWorkspaceLeaseStore(), SCOPE
    )

"""RRM-009 (composing RRM-008 F1): a family-admitted terminalization closes the ledger.

StageGraph terminalizes through its atomic family admission (`execute_family_admission`
with a `terminalize` action), not through a plain lifecycle command. The cancel it was
cancelled by must still be `applied` in the terminalizing commit, and every other pending
command must reach its terminal receipt, exactly as on the plain path. The production
cancellation drill found the gap (`tests/acceptance/control_plane/
test_rrm_009_production_cancellation.py`: the run was terminal `cancelled`, its cancel stayed
`delivered`).
"""

from __future__ import annotations

import pytest

from mission_control.application.execution.run_control_repository import (
    InMemoryRunControlRepository,
)
from mission_control.domain.policies.contracts import (
    RunOutcome,
    RunPhase,
)
from tests.support.unit.run_control.cancelled_terminalization_receipts import (
    assert_ledger_closed,
    cancelled_run,
    terminal_family_service,
    terminalize_through_the_family,
)


@pytest.mark.asyncio
async def test_family_admitted_cancelled_terminalization_applies_the_cancel() -> None:
    run_service = terminal_family_service(InMemoryRunControlRepository())
    run_id = await cancelled_run(run_service)
    receipt = await terminalize_through_the_family(run_service, run_id)
    await assert_ledger_closed(run_service, run_id, receipt)
    run = await run_service.get_run("tenant-1", run_id)
    assert (run.phase, run.terminal_outcome) == (RunPhase.TERMINAL, RunOutcome.CANCELLED)

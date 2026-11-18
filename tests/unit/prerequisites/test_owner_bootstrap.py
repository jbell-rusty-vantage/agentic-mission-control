"""Explicit paid bounds and digest-scoped bootstrap before a real worker is contacted."""

from unittest.mock import AsyncMock

import pytest

from mission_control.application.prerequisites.bootstrap_probe import (
    BootstrapProbeService,
    bootstrap_identity,
    bounded_probe_request,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.support.unit.prerequisites.owner_bootstrap import probe_template


def test_reviewed_pristine_template_gets_exact_runtime_unit_and_finite_segment():
    plan, operation = probe_template()
    request = bounded_probe_request(plan, operation)
    assert ProviderExecutionBinding.carried_by(
        request.operation
    ) == ProviderExecutionBinding.carried_by(operation)
    assert request.operation.effective_configuration_digest == plan.configuration_digest
    assert request.operation.runtime_unit.belllabs_run_id == plan.run_id
    assert request.segments.max_segments == 1
    assert request.timeout_seconds == 60
    assert operation.runtime_unit is None
    assert bootstrap_identity(plan) == bootstrap_identity(
        plan.model_copy(
            update={
                "prerequisite_id": "claude_managed.owner.m1",
                "purpose": "signal_receipt",
                "max_cost_micros": 1_000_000,
            }
        )
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"request_scope": "wrong-scope"},
        {"template_digest": "sha256:" + "0" * 64},
        {"configuration_digest": "sha256:" + "0" * 64},
        {"provider_binding_digest": "sha256:" + "0" * 64},
        {"max_cost_micros": 100_000},
        {"timeout_seconds": 30},
    ],
)
async def test_changed_scope_binding_or_bounds_never_starts_provider(changed):
    plan, operation = probe_template()
    port = AsyncMock()
    port.load.return_value = operation
    with pytest.raises(ValueError):
        await BootstrapProbeService(port).run(
            plan.model_copy(update=changed), paid_budget_micros=500_000
        )
    port.start.assert_not_awaited()
    port.prove.assert_not_awaited()


async def test_no_paid_authorization_never_loads_or_starts_and_success_uses_real_proof_port():
    plan, operation = probe_template()
    port = AsyncMock()
    with pytest.raises(ValueError, match="paid budget"):
        await BootstrapProbeService(port).run(plan, paid_budget_micros=0)
    port.load.assert_not_awaited()
    port.load.return_value = operation
    port.start.return_value = "workflow:actual"
    port.prove.return_value = "ingress:actual"
    assert await BootstrapProbeService(port).run(plan, paid_budget_micros=500_000) == {
        "workflow_id": "workflow:actual",
        "evidence_ref": "ingress:actual",
    }

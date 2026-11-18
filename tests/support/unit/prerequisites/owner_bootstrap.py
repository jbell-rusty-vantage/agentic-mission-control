"""Builders, constants and fakes that other test files import.

Moved from tests/unit/prerequisites/test_owner_bootstrap.py.
"""

from mission_control.application.prerequisites.bootstrap_probe import BootstrapProbePlan
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.fixtures.managed_lane import managed_binding, managed_operation


def probe_template():
    binding = managed_binding("sha256:" + "1" * 64)
    binding = ProviderExecutionBinding.sealed(
        **{
            **binding.model_dump(exclude={"binding_digest"}),
            "budgets": {"max_turns": 3, "max_segments": 1, "wall_clock_s": 60},
            "provider_options": {"provider": "claude_managed", "max_list_cost_minor_units": 50},
        }
    )
    operation = managed_operation(binding).model_copy(
        update={
            "tools": (),
            "mcp_servers": (),
            "secret_refs": (),
            "delegations": (),
            "budget_limits": {
                "currency.estimated_micros": 500_000,
                "time.elapsed_ms": 60_000,
                "tokens.total": 4000,
                "tool.calls.total": 8,
            },
        }
    )
    plan = BootstrapProbePlan(
        request_scope=operation.request_scope,
        run_id=operation.identity.run_id,
        semantic_input_binding_ref="binding",
        operation_request_key="probe",
        template_digest=sha256_digest(operation),
        configuration_digest=operation.effective_configuration_digest,
        provider_binding_digest=binding.binding_digest,
        purpose="signed_webhook",
        prerequisite_id="claude_managed.owner.ma2",
        prerequisite_digest="sha256:" + "2" * 64,
        max_cost_micros=500_000,
        timeout_seconds=60,
    )
    return plan, operation

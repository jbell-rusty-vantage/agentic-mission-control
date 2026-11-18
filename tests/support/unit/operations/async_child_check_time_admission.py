"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_async_child_check_time_admission.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.deep_agents.child_binding import seal_async_child_binding
from mission_control.adapters.deep_agents.routes import AGENT_FEATURES
from mission_control.application.subordinates.service import ProviderAsyncObservation
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.features import resolve_agent_configuration
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    AsyncSubagentDependencyClass,
    CapabilityGrant,
)
from tests.support.deep_agents import DeterministicProvider

TEXT = "canonical child result"


class ExactProvider(DeterministicProvider):
    """The deterministic provider with the adapter's exact output address for its text."""

    @staticmethod
    def _observation(
        status: str, run_id: str = "provider-run-1", receipt: str | None = None
    ) -> ProviderAsyncObservation:
        observation = DeterministicProvider._observation(status, run_id, receipt)
        if status != "success":
            return observation
        return observation.model_copy(
            update={
                "output_ref": "ref:async-output:" + sha256_digest(TEXT).removeprefix("sha256:"),
                "output_text": TEXT,
            }
        )


def _sealed_contract(model: Any, url: str = "http://agent-server.invalid") -> AsyncSubagentContract:
    configuration, _ = resolve_agent_configuration(
        AGENT_FEATURES,
        lane="deep_agents",
        model_provider=model.provider,
        sandbox_backend="state",
        lane_features=None,
        model_tools=None,
    )
    sealed = seal_async_child_binding(
        name="researcher",
        shape="seeded",
        system_prompt="Answer exactly what the objective asks.",
        model=model,
        tools=(),
        skills=(),
        mcp_servers=(),
        agent_configuration=configuration,
        authority_refs=("authority:parent-operation",),
        budget_limits={"tokens.total": 20},
    )
    return AsyncSubagentContract.create(
        contract_id=f"async-subagent:researcher:{sealed.sealed_digest}",
        name="researcher",
        description="Bounded background research",
        graph_id="belllabs_async_child",
        graph_revision="sealed-child@1",
        graph_binding_digest=sealed.sealed_digest,
        agent_protocol_url=url,
        deployment_credential_ref="environment:BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN",
        objective_schema_ref="schema:async-objective@1",
        result_schema_ref="schema:async-result@1",
        context_slice_id="context:child",
        state_slice_id="state:child",
        capability_ceiling=CapabilityGrant(capabilities=frozenset()),
        authority_refs=("authority:parent-operation",),
        budget_limits={"tokens.total": 20},
        dependency_classes=frozenset(
            {AsyncSubagentDependencyClass.NONBLOCKING, AsyncSubagentDependencyClass.ADVISORY}
        ),
        timeout_seconds=600,
        cancellation_propagation="required",
        late_result_policy="quarantine",
        fallback_policy="degrade",
        result_admission_policy_ref="policy:async-result:typed-manifest@1",
        child_binding=sealed,
    )

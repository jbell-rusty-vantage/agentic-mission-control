<!-- BEGIN:sdlc-module id=domain.execution -->
# Operation execution contracts
Provider-neutral operation execution contracts, no I/O. Covers execution and environment bindings, lane describe and turn payloads, the journal, checkpoint lineage, cognition points, materialization receipts, saved-result settlement and usage admission.
Entrypoints:
- contracts.py
- lanes.py — Lane contracts: mc.lane_describe.v1/.v2, the AgentHarness request and handle…
- bindings.py — Provider execution bindings: mc.execution_binding.v2, mc.environment_binding.v1…
- usage_admission.py — Quota/rate-limit dispositions, finite usage bounds and unknown cost
- checkpoint_lineage.py — CON-CP-CHECKPOINT-LINEAGE-V1: cognitive namespaces, stamps, and transition…
- cognition_points.py — mc.cognition_coordinate.v1, mc.cognition_point.v1 and mc.state_as_of.v1
- invocation_settlement.py — Saved provider results and their durable settlement
Also: environment_preparation.py, lane_turns.py, workspace_closure.py, network_policy.py, data_class.py, discovery.py, errors.py, materialization.py, async_subagent_reconciliation.py, lane_requirements.py, journal.py, approvals.py, history_reconciliation.py, async_child_admission.py, heartbeats.py (+8)
Tests: tests/unit/operations, tests/unit/harness, tests/conformance/lanes
Invariants:
- Provider-neutral: the contracts here name no provider SDK type.
- Settlement is by saved result and reducer; execution completion is not mission acceptance.
Explained by (docs/knowledge): lanes-and-harness, environment-preparation, environments, application-profile, budgets-and-usage, completion
Decided by (docs/adr): ADR-0005, ADR-0006, ADR-0010, ADR-0011, ADR-0017
Depends on: domain.authoring, domain.programs · Used by: application, adapters, adapters.deep_agents, adapters.temporal, adapters.postgres, adapters.cursor (+16)
Verify: uv run pytest tests/unit/operations tests/architecture
<!-- END:sdlc-module -->

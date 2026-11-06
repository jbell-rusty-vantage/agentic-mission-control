<!-- BEGIN:sdlc-module id=application.recovery -->
# Recovery, forks and reconciliation
Macro snapshots, semantic forks, reconciliation and terminal-evidence adoption. Also cognitive seeds, interventions and repairs, and closed-workflow cancellation recovery.
Entrypoints:
- cognitive_seed.py — Cognitive seeds for forks
- run_forks.py — Safe macro snapshots and semantic forks
- fork_seed.py — Seed a forked Run's first Context Packet
- terminal_evidence_adoption.py — Fenced adoption of an existing FINISHED Cursor run; no native harness dependency
- runtime_run_plan.py
- runtime_recovery.py
- closed_workflow.py — Reducer-governed cancellation recovery after the exact Temporal family closed
- graph_runtime_dispatch.py
- runtime_interventions.py
- runtime_execution_bindings.py
Also: runtime_reconciliation.py, runtime_resources.py, terminal_lane_adoption.py, runtime_bootstrap.py, runtime_decisions.py, terminal_evidence_capture.py, runtime_lineage.py, agent_server_actions.py, runtime_repairs.py, runtime_events.py, runtime_neutral_operations.py
Tests: tests/unit/recovery, tests/unit/continuation, tests/unit/runtime, tests/integration/postgres
Explained by (docs/knowledge): recovery, precise-fork, cross-provider-control
Decided by (docs/adr): ADR-0057, ADR-0069, ADR-0032
Depends on: domain, domain.authoring, domain.execution, contracts, domain.programs, application.programs (+1) · Used by: adapters.postgres, bootstrap, adapters.agent_server, adapters.temporal, application.missions, adapters (+2)
Verify: uv run pytest tests/unit/recovery tests/unit/continuation
<!-- END:sdlc-module -->

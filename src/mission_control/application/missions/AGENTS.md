<!-- BEGIN:sdlc-module id=application.missions -->
# Mission application handlers
Mission admission, lifecycle facade, inspection and run retrieval. Handlers over the durable runtime authority: scoped admission and governed launch, the facade over the reducer and boundary relay, and runtime saga adapters.
Entrypoints:
- service.py — One lifecycle facade over the existing transactional reducer and boundary relay
- inspection.py — Inspection enrichment
- runtime.py — Application-scoped adapters to the existing snapshot/fork/reconciliation sagas
- admission.py — Scoped admission and governed launch through the existing transactional services
- retrieval.py — Join existing run authorities without contacting a provider or creating another…
- completion_evidence.py — Read port for already committed, scope-bound completion validation receipts
Tests: tests/unit/mission_control, tests/unit/run_control, tests/integration/postgres/test_mission_control_lifecycle_postgres.py
Explained by (docs/knowledge): events-and-commands, lifecycle, budgets-and-usage, interventions, mission-control, recovery
Decided by (docs/adr): ADR-0032, ADR-0004, ADR-0008, ADR-0011, ADR-0001
Depends on: contracts, domain, application.recovery, domain.execution, application.programs, domain.frames (+1) · Used by: bootstrap, interfaces.http, interfaces.mcp, adapters.postgres, adapters.temporal, interfaces
Verify: uv run pytest tests/unit/mission_control tests/unit/run_control
<!-- END:sdlc-module -->

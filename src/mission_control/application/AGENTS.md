# Application logic

missions/service.py maps public controls to execution/service.py and boundary
delivery. missions/admission.py injects trusted admission fields and uses
execution/run_launch.py. missions/runtime.py delegates snapshots, forks and
reconciliation to recovery services.

authoring compiles definitions; programs coordinates family repositories;
execution owns lifecycle/journal/effects; subordinates coordinates delegated
submission and settlement; capabilities resolves admitted artifacts and tools.
installations/registry.py resolves immutable application bindings.

ports/payloads owns neutral content addresses and payload storage interfaces.
capabilities/catalog.py binds definition/search/discovery/inspection services;
external candidates remain unadmitted until governed registration.

Ports and framework-neutral logic belong here; concrete SDK clients and SQL
implementations belong in adapters. Composition belongs in bootstrap. Never choose
a provider fallback or install a permissive policy because a binding is missing.

Key proof: tests/unit/run_control/test_mission_control_*.py plus
tests/integration/postgres/test_mission_control_lifecycle_postgres.py and
test_mission_control_composition_postgres.py.

<!-- BEGIN:sdlc-module id=application -->
## Application logic
Use cases that map public controls to domain rules behind ports. Covers missions, execution, programs, recovery, subordinates and capabilities; concrete SDK clients and SQL belong in adapters, composition in bootstrap.
Entrypoints:
- execution/ — Application package: run_control
- authoring/ — Application package: control_plane
- frames/ — Native Event Store use cases: frame sink port, lane kind tables, writers
- outputs/ — Output submission application services
- programs/ — Application package: orchestration
- knowledge/ — Knowledge gateway application services: access, calls, gateway
- context/ — Context Pack Service: capture through ports, pack, render and persist
- subscriptions/
- environments/ — Execution-environment resolution, preparation attestation and network projection…
- missions/ — Mission Control application handlers over the durable runtime authority
Also: resolution/, agentic_components/, recovery/, workspaces/, reactions/, capabilities/, streams/, chains/, signals/, subordinates/, coordinator/, prerequisites/, selection/, watchers/, human_tasks/, artifacts/, secrets/, ports/, effects/, installations/
Tests: tests/unit/run_control, tests/integration/postgres/test_mission_control_lifecycle_postgres.py, tests/integration/postgres/test_mission_control_composition_postgres.py
Invariants:
- Never choose a provider fallback or install a permissive policy because a binding is missing.
Explained by (docs/knowledge): provider-frames-and-transcript, lanes-and-harness, mission-chains, capabilities, interventions, mission-stream
Decided by (docs/adr): ADR-0054, ADR-0004, ADR-0005, ADR-0006, ADR-0008
Depends on: domain, domain.execution, domain.authoring, domain.frames, contracts, domain.programs (+5) · Used by: bootstrap, adapters.temporal, adapters, adapters.postgres, adapters.cursor, interfaces.http (+7)
Verify: uv run pytest tests/unit/run_control
<!-- END:sdlc-module -->

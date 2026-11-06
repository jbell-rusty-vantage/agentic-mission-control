# General runtime navigation

Read root AGENTS.md and docs/knowledge/index.md before broad changes.
contracts owns public envelopes; domain owns meaning; application owns use cases;
adapters owns concrete I/O; interfaces owns transport; bootstrap owns composition.

A request becomes an admitted immutable binding, then a scoped Temporal root,
family decisions, bounded operations and durable settlements. Interpreters propose;
reducers authorize and terminalize. Keep provider objects outside domain.
Application-specific integrations belong outside this package.

Source-relative files are runtime code; experiments/ at repository root is not
shipped as the production kernel. Check tests/unit for contracts and reducers,
tests/integration for stores/runtime and tests/acceptance/mission_control for
authenticated end-to-end proofs.

<!-- BEGIN:sdlc-module id=mission_control -->
## General runtime navigation
Runtime layers: contracts, domain, application, adapters, interfaces, bootstrap. A request becomes an admitted immutable binding, then a scoped Temporal root, family decisions, bounded operations and durable settlements.
Entrypoints:
- application/ — Application services and persistence ports
- adapters/
- domain/ — Application-owned domain contracts
- interfaces/
- bootstrap/
- contracts/ — Framework-neutral Mission Control public contracts
Tests: tests/unit, tests/integration, tests/acceptance/mission_control, tests/architecture
Invariants:
- Interpreters propose; reducers authorize and terminalize.
- Provider objects stay outside the domain; application-specific integrations stay outside this package.
Explained by (docs/knowledge): mission-control
Decided by (docs/adr): ADR-0001, ADR-0002, ADR-0004, ADR-0005, ADR-0007
Verify: make check; make typecheck
<!-- END:sdlc-module -->

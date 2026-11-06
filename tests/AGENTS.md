# Verification navigation

unit proves pure contracts, reducers and isolated errors. integration proves
concrete persistence and runtime boundaries. acceptance/mission_control proves
authenticated scoped execution with real local PostgreSQL and Temporal.
qualification/two_project is the reviewer-owned independent proof of the common
release; its common_db tests fail, never skip, without MISSION_CONTROL_TEST_ADMIN_DSN.

Do not hide a missing service behind a new default skip. Report environment gates
and exact selections. Disable external tracing in deterministic tests and never
spend provider budget without authorization. Never point destructive fixture setup
at live or unknown databases; generate isolated local database names.

A source reorganization requires import, packaging and renewed runtime checks.
Do not sum overlapping suite counts or claim deployment from local execution.

<!-- BEGIN:sdlc-module id=tests -->
## Verification navigation
Where each kind of proof lives. unit covers pure contracts and reducers, integration real PostgreSQL and Temporal boundaries, acceptance/mission_control authenticated scoped execution, conformance every lane against its fake, qualification/two_project the common release.
Entrypoints:
- unit/
- integration/
- acceptance/
- conformance/
- fixtures/
- qualification/
- architecture/
- experiments/ — Isolated experiment tests
- conftest.py
- schema_context_helpers.py
Also: golden/
Tests: tests/architecture/test_package_boundaries.py
Invariants:
- Never hide a missing service behind a new default skip.
- Destructive fixture setup never targets live or unknown databases.
Explained by (docs/knowledge): cursor-lane, interventions, lanes-and-harness, budgets-and-usage, context-and-continuation, environment-preparation
Decided by (docs/adr): ADR-0018, ADR-0019, ADR-0030, ADR-0031, ADR-0005
Verify: make check; make test-integration; make test-qualification (needs MISSION_CONTROL_TEST_ADMIN_DSN)
<!-- END:sdlc-module -->

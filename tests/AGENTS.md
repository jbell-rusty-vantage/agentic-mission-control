# Verification navigation

- `unit/` pure contracts, reducers, isolated errors; `architecture/` package rules;
  `conformance/` every lane against its fake (all in `make check`).
- `integration/` real PostgreSQL 17 and Temporal; `acceptance/mission_control/` authenticated
  scoped execution on both; `qualification/two_project/` the common release (common_db
  tests fail, never skip, without MISSION_CONTROL_TEST_ADMIN_DSN).
- `support/` holds every helper: builders, the disposable-database plugin (`db.py`,
  `db_plugin.py`), `temporal.py` (`workflow_env`), `stack.py`, scripted models, `providers/`
  (one fake per provider API), `contracts/` (in-memory vs PostgreSQL scenarios), `scenarios/`.
  Mirror modules under `support/{unit,integration,acceptance}/` serve one test file each.
- `fixtures/` holds data only: histories, manifests, goldens, recorded frames, custody sources.
- Biotech-domain tests live in `integrations/biotech/tests`: `uv run --group biotech pytest
  integrations/biotech/tests` (`make test-biotech`); the seven BIOTECH_SCHEMA_SDL_PATH tests skip.

Fake only what we do not control (models, provider APIs, Knowledge Services, clock), with one
double per boundary; use real PostgreSQL and Temporal, and an in-memory port only beside a
shared contract test ([RECOMMENDATION section 1](../docs/specs/agentic-sdlc-2026-11/test-suite-review-2026-11-17/RECOMMENDATION.md#1-how-to-decide-what-a-test-may-fake)).
Never patch privates or assert internal calls. Name test files by behaviour, uniquely.

Do not hide a missing service behind a new default skip; report gates and exact selections.
No provider spend without authorization; destructive setup only on generated `mct_*` names.

<!-- BEGIN:sdlc-module id=tests -->
## Verification navigation
Where each kind of proof lives. unit covers pure contracts and reducers, integration real PostgreSQL and Temporal boundaries, acceptance/mission_control authenticated scoped execution, conformance every lane against its fake, qualification/two_project the common release.
Entrypoints:
- unit/
- integration/
- acceptance/
- conformance/
- qualification/
- fixtures/
- architecture/
- support/
- schema_context_helpers.py
- conftest.py
Also: golden/
Tests: tests/architecture/test_package_boundaries.py
Invariants:
- Never hide a missing service behind a new default skip.
- Destructive fixture setup never targets live or unknown databases.
Explained by (docs/knowledge): interventions, lanes-and-harness, cursor-lane, budgets-and-usage, context-and-continuation, environment-preparation
Decided by (docs/adr): ADR-0018, ADR-0019, ADR-0030, ADR-0031, ADR-0005
Verify: make check; make test-integration; make test-qualification (needs MISSION_CONTROL_TEST_ADMIN_DSN)
<!-- END:sdlc-module -->

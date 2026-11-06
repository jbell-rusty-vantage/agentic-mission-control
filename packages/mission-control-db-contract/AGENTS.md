# mission-control-db-contract agent guide

This package owns the common Mission Control SQL (ADR-0003). The runtime never imports it;
`mission-db` is admin tooling that installs, verifies and seeds a release into one application
database. Read the root `GLOSSARY.md` and `docs/knowledge/persistence.md` first.

## Where things are

| Concern | Start |
| --- | --- |
| CLI commands (release-build, lock, inspect, plan, apply, verify, seed-plan/apply, runtime-plan/apply, login-plan/apply, tenant-plan/apply, snapshot, compare, qualify) | src/mission_control_db_contract/cli.py; restricted LOGIN roles in logins.py; deployment tenants in tenants.py |
| Releases (the only release authority; new SQL = a new version directory) | releases/<version>/component/ (newest built 1.14.0; newest deployment locks 1.9.0), releases/README.md; release inputs in ../../scripts/release_1130/ and release_1140/ |
| Retired input (frozen 1.4.0; never build, lock or install from it) | component/ |
| Generated contract, manifest, fingerprint | releases/<version>/component/{generated,manifest.json}, src/.../fingerprint.py, release.py |
| Seeds per application and qualification | seeds/common, seeds/biotech, seeds/ai-engineer, seeds/qualification |
| Runtime persistence descriptor (LangGraph saver/store schema) | runtime/descriptor.json, runtime/AGENT_SERVER_TOPOLOGY.md |
| App targets (project ref, installation id, DSN env var name, approval) | ../../deployments/<app>/target.toml and release.lock.json |
| Tests (disposable clusters, repeat apply, mismatch, isolation) | tests/ |

## Invariants

A release is immutable once applied: never edit migration bytes or an applied seed; add a new
component version and a new seed version (`mc.app.bindings@1.0.0` is frozen, 1.0.1 is current).
Every apply, runtime-apply and seed-apply writes a receipt; verify compares the persisted
fingerprint and contract digest. Protected objects outside the three schemas must not change.
Runtime persistence targets a separate app-bound database (ADR-0017); the descriptor stays here.

## Verify

`uv run pytest packages/mission-control-db-contract/tests` against a disposable PostgreSQL 17 +
pgvector with `MISSION_CONTROL_TEST_ADMIN_DSN` set; `mission-db qualify` for a two-target proof.
Apply, seed and role changes run on disposable targets in the same session (startup delivery mode); never against a production
application project. Read BellLabs `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` before touching a Supabase project, and
[releases/README.md](releases/README.md) for the release notes. The October 2026 live plan is archived.

<!-- BEGIN:sdlc-module id=db_contract -->
## Common database component
Common SQL, releases and the mission-db admin tool (ADR-0003). Holds immutable releases and seeds; mission-db installs, verifies and seeds a release into one application database. The runtime never imports it.
Entrypoints:
- component/
- tests/
- seeds/
- releases/
- src/
- runtime/
- scripts/
- bundle-sources/
- pyproject.toml
Tests: packages/mission-control-db-contract/tests
Invariants:
- A release is immutable once applied: add a new component version and seed version, never edit bytes.
- Every apply, runtime-apply and seed-apply writes a receipt; verify compares fingerprint and contract digest.
Explained by (docs/knowledge): persistence, capability-seeds, capabilities, completion, database-component, environment-preparation
Decided by (docs/adr): ADR-0002, ADR-0003, ADR-0009, ADR-0023, ADR-0033
Verify: make test-db-contract (disposable PostgreSQL 17 + pgvector, MISSION_CONTROL_TEST_ADMIN_DSN set); mission-db qualify (two-target proof)
<!-- END:sdlc-module -->
